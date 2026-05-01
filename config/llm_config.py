"""
Configuración del LLM (Ollama Cloud)
"""
import os
import requests
from typing import Optional

OLLAMA_ENDPOINT = os.getenv("OLLAMA_CLOUD_ENDPOINT", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_CLOUD_MODEL", "mistral")

def call_ollama_cloud(
    messages: list,
    tools: Optional[list] = None,
    temperature: float = 0.7,
    max_tokens: int = 1024
) -> dict:
    """
    Llama a Ollama Cloud con soporte para tools/function calling
    
    Args:
        messages: Lista de mensajes en formato OpenAI
        tools: Lista de tool schemas (opcional)
        temperature: Temperatura del modelo
        max_tokens: Max tokens en la respuesta
    
    Returns:
        dict con status, content, stop_reason y full_response
    """
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    
    if tools:
        payload["tools"] = tools
    
    try:
        response = requests.post(
            f"{OLLAMA_ENDPOINT}/api/chat",
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        data = response.json()
        
        return {
            "status": "success",
            "content": data.get("message", {}).get("content", ""),
            "stop_reason": data.get("message", {}).get("stop_reason", "end_turn"),
            "full_response": data
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": f"Ollama Cloud error: {str(e)}"
        }
