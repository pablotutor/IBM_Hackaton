# SmartProc AI — Procurement Copilot

Agente IA para optimizar el proceso de compras en empresas Telco.

## 🎯 Objetivo

Ayudar a compradores con recomendaciones inteligentes sobre:
- Detección de duplicados en catálogo
- Cumplimiento de cuota de proveedores
- Detección de maverick spend
- Validación de precio contra benchmark histórico + ML
- Evaluación de impacto ESG del proveedor

## 🏗️ Arquitectura

Ver `ARCHITECTURE.md` para diagrama y descripción detallada.

## 🛠️ Stack tecnológico

- **LLM**: Ollama Cloud (Mistral o Llama)
- **Agente**: LangGraph + LangChain
- **Embeddings**: sentence-transformers
- **Vector store**: ChromaDB
- **ML**: XGBoost
- **Frontend**: Streamlit
- **Datos**: CSVs + PDFs sintéticos

## 🚀 Quick start

```bash
# Setup
python3.11 -m venv venv
source venv/bin/activate
pip install -e .

# Generar datos (incluye la canonicalización del catálogo)
jupyter notebook notebooks/01_generate_synthetic_data.ipynb
# o, si ya hay datos, solo (re)canonicalizar:
python scripts/build_canonical_ids.py

# Correr la app
streamlit run frontend/app.py        # o: uvicorn api.server:app --reload
```

## 📁 Estructura de carpetas
```
smartproc-copilot/
├── data/
│   ├── raw/
│   ├── processed/
│   └── synthetic/          # Dataset generado
│       ├── catalog.csv      # 200 SKUs = 89 productos reales (+canonical_id/canonical_name)
│       ├── contracts.json
│       ├── transactions.csv
│       ├── forecast.csv
│       ├── esg_scores.json  # Scores ESG de 27 proveedores
│       └── contracts/       # TXT de contratos (RAG)
├── agents/                 # Lógica del agente LangGraph (graph.py, prompts.py)
├── tools/                  # Las 6 tools
│   ├── catalog_search.py   # RAG + agrupación por canonical_id
│   ├── contract_lookup.py  # RAG — contratos marco
│   ├── quota_status.py     # SQL — cuota de proveedor
│   ├── price_benchmark.py  # ML  — precio justo
│   ├── sustainability_score.py  # SQL — score ESG
│   └── recommend_variant.py     # Scoring determinista — ganador entre duplicados
├── scripts/                # build_canonical_ids.py (canonicalización offline)
├── api/                    # FastAPI (server.py) para el frontend React
├── config/                 # Configuración (LLM, etc.)
├── frontend/               # App Streamlit + index.html (React)
├── notebooks/              # Jupyter notebooks
├── eval/                   # Eval set y métricas
├── README.md
├── ARCHITECTURE.md
├── TOOLS_SPEC.md
├── pyproject.toml
└── .env.example
```

## 🧬 Resolución de duplicados

El catálogo tiene duplicados (mismo producto, distinto SKU/proveedor/precio). En vez de detectarlos en cada búsqueda, se resuelven **offline**: `scripts/build_canonical_ids.py` asigna un `canonical_id` a cada artículo (Tier 1 nombre exacto + Tier 2 matching semántico). `catalog_search` agrupa por ese id y `recommend_variant` elige el ganador del grupo (contrato → precio → cuota → ESG). Resultado: **200 SKUs → 89 productos reales**.

## 📖 Documentación

- `ARCHITECTURE.md`: Diagrama y descripción de la solución
- `TOOLS_SPEC.md`: Especificación exacta de las 6 tools