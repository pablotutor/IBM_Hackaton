"""
Agente LangGraph — SmartProc Copilot.

Arquitectura ReAct:
  START → agent → [tool_calls?] → tools → agent → ... → END

El agente recibe la solicitud del comprador, orquesta las 4 tools en el orden
óptimo y genera una recomendación final estructurada.
"""

import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from tools import ALL_TOOLS
from agents.prompts import SYSTEM_PROMPT

load_dotenv()

# ── Configuración del LLM ─────────────────────────────────────────────────────

def _build_llm():
    endpoint = os.getenv("OLLAMA_CLOUD_ENDPOINT", "http://localhost:11434")
    model    = os.getenv("OLLAMA_CLOUD_MODEL", "mistral")
    return ChatOllama(
        base_url=endpoint,
        model=model,
        temperature=0.1,
        num_predict=2048,
    ).bind_tools(ALL_TOOLS, tool_choice="auto")


# ── Nodos del grafo ───────────────────────────────────────────────────────────

def call_model(state: MessagesState) -> dict:
    """Nodo principal: el LLM razona y decide qué tools llamar (o responde)."""
    llm = _build_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(ALL_TOOLS)


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_agent():
    """Construye y compila el grafo LangGraph. Llama una sola vez al arrancar."""
    graph = StateGraph(MessagesState)

    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")

    # Si el LLM emitió tool_calls → ejecutar tools; si no → terminar
    graph.add_conditional_edges(
        "agent",
        tools_condition,                     # built-in: revisa si hay tool_calls
        {"tools": "tools", END: END},
    )

    # Tras ejecutar tools, volver al agente para razonar sobre los resultados
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── Interfaz pública ──────────────────────────────────────────────────────────

# Singleton del grafo compilado (se reutiliza entre peticiones)
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def run_agent_streaming(user_message: str, buyer_id: str = "buyer_mad_001"):
    """
    Ejecuta el agente en modo streaming y hace yield de eventos para la UI.

    Yields dicts con:
        {"type": "tool_start",  "tool": str,  "inputs": dict}
        {"type": "tool_end",    "tool": str,  "output": str}
        {"type": "agent_token", "token": str}
        {"type": "done",        "final_response": str, "tool_calls_log": list}
    """
    agent = get_agent()

    enriched = (
        f"{user_message}\n\n[Contexto del sistema: buyer_id del comprador activo = '{buyer_id}']"
    )
    input_state = {"messages": [HumanMessage(content=enriched)]}

    final_response  = ""
    tool_calls_log  = []

    for event in agent.stream(input_state, stream_mode="updates"):
        for node_name, state_update in event.items():

            if node_name == "tools":
                for msg in state_update.get("messages", []):
                    if hasattr(msg, "name") and hasattr(msg, "content"):
                        # Asociar output al último tool_start pendiente
                        for entry in reversed(tool_calls_log):
                            if entry["tool"] == msg.name and "output" not in entry:
                                entry["output"] = msg.content
                                break
                        yield {
                            "type":   "tool_end",
                            "tool":   msg.name,
                            "output": msg.content,
                        }

            elif node_name == "agent":
                ai_msg = state_update.get("messages", [None])[-1]
                if ai_msg is None:
                    continue

                if hasattr(ai_msg, "tool_calls") and ai_msg.tool_calls:
                    for tc in ai_msg.tool_calls:
                        entry = {"tool": tc["name"], "inputs": tc["args"]}
                        tool_calls_log.append(entry)
                        yield {"type": "tool_start", "tool": tc["name"], "inputs": tc["args"]}

                if hasattr(ai_msg, "content") and ai_msg.content:
                    final_response = ai_msg.content
                    yield {"type": "agent_token", "token": ai_msg.content}

    yield {"type": "done", "final_response": final_response, "tool_calls_log": tool_calls_log}


def invoke_agent(user_message: str, buyer_id: str = "buyer_mad_001") -> dict:
    """
    Ejecuta el agente de forma síncrona (sin streaming).
    Devuelve el estado final con todos los mensajes.
    """
    agent = get_agent()

    enriched = (
        f"{user_message}\n\n[Contexto del sistema: buyer_id del comprador activo = '{buyer_id}']"
    )
    final_state = agent.invoke({"messages": [HumanMessage(content=enriched)]})

    # Extraer respuesta final y tool calls del historial
    tool_calls_log = []
    final_response = ""

    for msg in final_state["messages"]:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls_log.append({"tool": tc["name"], "inputs": tc["args"]})
            if msg.content:
                final_response = msg.content
        elif hasattr(msg, "name") and hasattr(msg, "content"):
            # ToolMessage
            for entry in tool_calls_log:
                if entry["tool"] == msg.name and "output" not in entry:
                    entry["output"] = msg.content
                    break

    return {
        "response":       final_response,
        "tool_calls_log": tool_calls_log,
        "messages":       final_state["messages"],
    }
