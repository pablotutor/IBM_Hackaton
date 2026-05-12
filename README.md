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

# Generar datos
jupyter notebook notebooks/01_generate_synthetic_data.ipynb

# Correr la app
streamlit run frontend/app.py
```

## 📁 Estructura de carpetas
```
smartproc-copilot/
├── data/
│   ├── raw/
│   ├── processed/
│   └── synthetic/          # Dataset generado
│       ├── catalog.csv
│       ├── contracts.json
│       ├── transactions.csv
│       ├── forecast.csv
│       ├── esg_scores.json  # Scores ESG de 27 proveedores
│       └── contracts/       # TXT de contratos (RAG)
├── agents/                 # Lógica del agente LangGraph
├── tools/                  # Las 5 tools
│   ├── catalog_search.py   # RAG — duplicados en catálogo
│   ├── contract_lookup.py  # RAG — contratos marco
│   ├── quota_status.py     # SQL — cuota de proveedor
│   ├── price_benchmark.py  # ML  — precio justo
│   └── sustainability_score.py  # SQL — score ESG
├── config/                 # Configuración (LLM, etc.)
├── frontend/               # App Streamlit
├── notebooks/              # Jupyter notebooks
├── eval/                   # Eval set y métricas
├── README.md
├── ARCHITECTURE.md
├── TOOLS_SPEC.md
├── pyproject.toml
└── .env.example
```

## 📖 Documentación

- `ARCHITECTURE.md`: Diagrama y descripción de la solución
- `TOOLS_SPEC.md`: Especificación exacta de las 5 tools