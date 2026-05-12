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
streamlit run frontend/app.py            # arrancar la app
pytest eval/                             # correr evaluación
```

## Estructura y estado de implementación

```
data/
  synthetic/      # catalog.csv, contracts.json, transactions.csv, forecast.csv
  raw/            # vacío
  processed/      # vacío
agents/           # agente LangGraph principal — POR IMPLEMENTAR
tools/            # las 4 tools — POR IMPLEMENTAR
  catalog_search.py
  contract_lookup.py
  quota_status.py
  price_benchmark.py
config/
  llm_config.py   # call_ollama_cloud() — ya implementado
frontend/
  app.py          # Streamlit — POR IMPLEMENTAR
eval/             # test set y métricas — POR IMPLEMENTAR
notebooks/
  01_generate_synthetic_data.ipynb  # stub — POR IMPLEMENTAR
```

## Orden de implementación

1. `notebooks/01_generate_synthetic_data.ipynb` — generar datos (todo lo demás depende de esto)
2. `tools/` — implementar las 4 tools según `TOOLS_SPEC.md`
3. `agents/` — agente LangGraph que orquesta las tools
4. `frontend/app.py` — chat Streamlit con panel de razonamiento
5. `eval/` — test set y métricas

## Las 5 tools (ver TOOLS_SPEC.md para firmas exactas)

| Tool | Técnica | Input clave | Output clave |
|---|---|---|---|
| `catalog_search` | RAG + embeddings | `description`, `limit` | resultados + `duplicates_detected` |
| `contract_lookup` | RAG sobre JSONs | `category` | contratos vigentes |
| `quota_status` | Query a CSV | `buyer_id`, `supplier`, `category` | `current_market_share` vs `target` |
| `price_benchmark` | XGBoost | `sku`, `quantity`, `supplier` | `estimated_fair_price`, `confidence` |
| `sustainability_score` | Query SQL (pandas) | `supplier`, `category` | `esg_score` (0-100), breakdown, certificaciones |

## Convenciones

- Todas las tools validan inputs con Pydantic
- Todas devuelven `{"status": "success/error", ...}` — nunca lanzan excepciones sin capturar
- Timeout por tool: 5 segundos
- Datos sintéticos: 200 artículos catálogo (20 duplicados), 5 contratos, 2000 transacciones, 27 proveedores ESG
- Tools con datos estructurados (scores, booleanos, fechas) usan query SQL/pandas — no RAG

## Variables de entorno (.env)

```
OLLAMA_CLOUD_ENDPOINT=https://...
OLLAMA_CLOUD_MODEL=mistral
OLLAMA_CLOUD_API_KEY=
LANGSMITH_API_KEY=          # opcional
LANGSMITH_PROJECT=smartproc-dev
LOG_LEVEL=INFO
```
