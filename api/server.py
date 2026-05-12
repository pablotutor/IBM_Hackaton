"""
Orbita — FastAPI server
Expone el agente LangGraph como API HTTP con Server-Sent Events (SSE).
Sirve también el frontend estático desde frontend/.
"""
import asyncio
import json
import os
import re
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Resolver paths antes de importar el agente
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# macOS: evitar segfault de PyTorch/sentence-transformers
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from agents.graph import run_agent_streaming  # noqa: E402
from tools.catalog_search import catalog_search  # noqa: E402

app = FastAPI(title="Orbita", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    buyer_id: str = "buyer_mad_001"


@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("OLLAMA_CLOUD_MODEL", "unknown")}


@app.post("/api/chat")
async def chat_stream(req: ChatRequest):
    """
    Stream de eventos SSE del agente.
    Cada línea: data: <JSON>\n\n
    Eventos: tool_start | tool_end | agent_token | done
    """
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def _run():
        try:
            for event in run_agent_streaming(req.message, req.buyer_id):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": str(e)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    threading.Thread(target=_run, daemon=True).start()

    async def generate():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


class CatalogCheckRequest(BaseModel):
    message: str


@app.post("/api/catalog-check")
def catalog_check(req: CatalogCheckRequest):
    """
    Pre-flight: extrae la descripción del producto del mensaje del comprador
    y llama a catalog_search para detectar SKUs duplicados antes de arrancar el agente.
    Falla abierto: cualquier error devuelve duplicates_detected=0.
    """
    text = req.message.strip()
    text = re.sub(r'^\d[\d.,]*\s*(?:m|km|u|unidades?|uds?\.?|ud\.?)\s+de\s+', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+a\s+[\d.,]+\s*€.*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*[¿?][^?]*\??\s*$', '', text).strip()
    query = text if len(text) >= 10 else req.message.strip()

    try:
        result = catalog_search.func(description=query, limit=7)
    except Exception:
        return {"duplicates_detected": 0, "items": [], "query": query}

    if result.get("status") != "success":
        return {"duplicates_detected": 0, "items": [], "query": query}

    items = [
        {
            "sku":              r["sku"],
            "name":             r["name"],
            "supplier":         r["supplier"],
            "unit_price_eur":   r["unit_price_eur"],
            "uom":              r["uom"],
            "similarity_score": r["similarity_score"],
            "is_duplicate":     r["is_duplicate"],
        }
        for r in result.get("results", [])
    ]
    return {
        "duplicates_detected": result.get("duplicates_detected", 0),
        "items":               items,
        "query":               query,
    }


# Servir el frontend estático (debe ir al final para no solapar rutas /api)
_frontend_dir = PROJECT_ROOT / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="static")
