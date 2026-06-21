# CLAUDE.md — SmartProc Copilot

Procurement Copilot para empresas Telco. Hackathon IBM. Agente IA que ayuda a compradores con recomendaciones inteligentes sobre catálogo, contratos, cuotas y precios.

## Stack

- **LLM**: Ollama Cloud (Mistral/Llama) vía `config/llm_config.py` — endpoint en `.env`
- **Agente**: LangGraph + LangChain
- **Embeddings**: sentence-transformers (local)
- **Vector store**: ChromaDB (local)
- **ML**: XGBoost (price_benchmark)
- **Frontend**: Streamlit (`frontend/app.py`)
- **Python**: 3.11, venv en `venv/`

## Comandos clave

```bash
source venv/bin/activate
pip install -e .                          # instalar dependencias
jupyter notebook notebooks/              # generar datos sintéticos primero
python scripts/build_canonical_ids.py    # canonicalizar catálogo (resolución de duplicados)
streamlit run frontend/app.py            # arrancar la app (o: uvicorn api.server:app)
pytest eval/                             # correr evaluación
```

## Estructura y estado de implementación

```
data/
  synthetic/      # catalog.csv (+canonical_id/canonical_name), contracts.json, transactions.csv, forecast.csv, esg_scores.json
  raw/            # vacío
  processed/      # vacío
agents/           # agente LangGraph principal
  graph.py        # grafo ReAct + slimming de tool outputs
  prompts.py      # system prompt (protocolo de 2 rondas)
tools/            # las 6 tools
  catalog_search.py
  contract_lookup.py
  quota_status.py
  price_benchmark.py
  sustainability_score.py
  recommend_variant.py
scripts/
  build_canonical_ids.py  # pipeline de canonicalización del catálogo (offline)
config/
  llm_config.py   # call_ollama_cloud() — ya implementado
frontend/
  app.py          # Streamlit
  index.html      # frontend React (servido por api/server.py)
api/
  server.py       # FastAPI: /api/chat-stream, /api/catalog-check
eval/             # test set y métricas — POR IMPLEMENTAR
notebooks/
  01_generate_synthetic_data.ipynb  # genera datos + canonicaliza el catálogo
```

## Orden de implementación

1. `notebooks/01_generate_synthetic_data.ipynb` — generar datos + canonicalizar (todo lo demás depende de esto)
2. `tools/` — implementar las 6 tools según `TOOLS_SPEC.md`
3. `agents/` — agente LangGraph que orquesta las tools
4. `frontend/` — chat (Streamlit `app.py` o React `index.html` + `api/server.py`)
5. `eval/` — test set y métricas

## Las 6 tools (ver TOOLS_SPEC.md para firmas exactas)

| Tool | Técnica | Input clave | Output clave |
|---|---|---|---|
| `catalog_search` | RAG + embeddings + agrupación por `canonical_id` | `description`, `limit` | `groups` (variantes por producto) + `duplicate_groups_detected` |
| `contract_lookup` | RAG sobre JSONs | `category` | contratos vigentes |
| `quota_status` | Query a CSV | `buyer_id`, `supplier`, `category` | `current_market_share` vs `target` |
| `price_benchmark` | XGBoost | `sku`, `quantity`, `supplier` | `estimated_fair_price`, `confidence` |
| `sustainability_score` | Query SQL (pandas) | `supplier`, `category` | `esg_score` (0-100), breakdown, certificaciones |
| `recommend_variant` | Scoring determinista (orquesta las 4 anteriores) | `canonical_id`, `buyer_id`, `quantity` | `winner` + `recommendation_score`, `why`, `ranking` |

## Resolución de duplicados (clave del producto)

La duplicación es propiedad **del catálogo**, no de cada búsqueda. `scripts/build_canonical_ids.py` asigna offline un `canonical_id`/`canonical_name` a cada artículo:
- **Tier 1 (exacto):** agrupa por nombre normalizado (~90% del catálogo; la serie `EXT-*` es un espejo).
- **Tier 2 (semántico):** los `*-DUP-*` parafraseados se enganchan a su canónico por embedding (bloqueo por `category`+`uom`).

`catalog_search` solo agrupa por `canonical_id`; `recommend_variant` elige el ganador del grupo con jerarquía **contrato → precio → cuota → ESG** (determinista, no lo calcula el LLM). Resultado: 200 SKUs → 89 productos reales.

## Convenciones

- Todas las tools validan inputs con Pydantic
- Todas devuelven `{"status": "success/error", ...}` — nunca lanzan excepciones sin capturar
- Timeout por tool: 5 segundos
- Datos sintéticos: 200 artículos catálogo = 89 productos reales (111 variantes redundantes: 91 espejo `EXT-*` + 20 `*-DUP-*` parafraseados), 5 contratos, 2000 transacciones, 27 proveedores ESG
- Tools con datos estructurados (scores, booleanos, fechas) usan query SQL/pandas — no RAG
- La detección de duplicados es offline (`canonical_id`), no en tiempo de búsqueda

## Variables de entorno (.env)

```
OLLAMA_CLOUD_ENDPOINT=https://...
OLLAMA_CLOUD_MODEL=mistral
OLLAMA_CLOUD_API_KEY=
LANGSMITH_API_KEY=          # opcional
LANGSMITH_PROJECT=smartproc-dev
LOG_LEVEL=INFO
```
