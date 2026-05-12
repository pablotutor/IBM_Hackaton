"""
Agente LangGraph — SmartProc Copilot.

Arquitectura ReAct:
  START → agent → [tool_calls?] → tools → agent → ... → END

El agente recibe la solicitud del comprador, orquesta las 4 tools en el orden
óptimo y genera una recomendación final estructurada.
"""

import os
import time
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode, tools_condition

from tools import ALL_TOOLS
from agents.prompts import SYSTEM_PROMPT

load_dotenv()

_MAX_RETRIES = 3
_RETRY_DELAY = 2  # segundos entre reintentos

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
    """Nodo principal: el LLM razona y decide qué tools llamar (o responde).
    Reintenta hasta _MAX_RETRIES veces en errores 5xx transitorios de Ollama Cloud."""
    llm = _build_llm()
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = llm.invoke(messages)
            return {"messages": [response]}
        except Exception as e:
            err = str(e)
            # Reintentar solo en errores de servidor transitorios (5xx)
            if any(code in err for code in ("500", "502", "503", "504")):
                last_exc = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            raise  # errores no transitorios: relanzar inmediatamente

    raise last_exc


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


def _extract_text(msg) -> str:
    """Extrae texto de un AIMessage (content puede ser str o lista de bloques)."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        ).strip()
    return ""


def run_agent_streaming(user_message: str, buyer_id: str = "buyer_mad_001"):
    """
    Ejecuta el agente en modo streaming y hace yield de eventos para la UI.

    Usa stream_mode="values" para tener siempre el estado completo en cada paso,
    lo que permite extraer la respuesta final del historial aunque el LLM devuelva
    content="" en el último turno de tools.

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

    tool_calls_log   = []
    seen_tool_ids    = set()   # evita emitir tool_start duplicados
    seen_result_ids  = set()   # evita emitir tool_end duplicados
    final_state_msgs = []      # historial completo del último estado

    for state in agent.stream(input_state, stream_mode="values"):
        messages = state.get("messages", [])
        final_state_msgs = messages  # siempre guardamos el estado más reciente

        last = messages[-1] if messages else None
        if last is None:
            continue

        # ── AIMessage con tool_calls → emitir tool_start ──────────────────
        if isinstance(last, AIMessage) and last.tool_calls:
            for tc in last.tool_calls:
                uid = tc.get("id") or tc["name"]
                if uid not in seen_tool_ids:
                    seen_tool_ids.add(uid)
                    entry = {"tool": tc["name"], "inputs": tc["args"]}
                    tool_calls_log.append(entry)
                    yield {"type": "tool_start", "tool": tc["name"], "inputs": tc["args"]}

        # ── ToolMessage → emitir tool_end ─────────────────────────────────
        elif hasattr(last, "tool_call_id") and hasattr(last, "content"):
            rid = getattr(last, "tool_call_id", None) or id(last)
            if rid not in seen_result_ids:
                seen_result_ids.add(rid)
                tool_name = getattr(last, "name", "")
                for entry in reversed(tool_calls_log):
                    if entry["tool"] == tool_name and "output" not in entry:
                        entry["output"] = last.content
                        break
                yield {"type": "tool_end", "tool": tool_name, "output": last.content}

    # ── Extraer respuesta final del historial completo ────────────────────
    # Buscamos el último AIMessage sin tool_calls y con texto no vacío.
    final_response = ""
    for msg in reversed(final_state_msgs):
        if isinstance(msg, AIMessage) and not msg.tool_calls:
            text = _extract_text(msg)
            if text:
                final_response = text
                break

    if final_response:
        yield {"type": "agent_token", "token": final_response}

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
