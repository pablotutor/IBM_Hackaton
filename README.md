# Orbita — Procurement Copilot

Agente IA para optimizar el proceso de compras en empresas Telco. El comprador escribe en lenguaje natural lo que quiere comprar y Orbita orquesta 6 herramientas para devolver una recomendación accionable: qué SKU comprar, a qué proveedor, a qué precio y por qué.

## 🎯 Qué puede hacer

Dada una petición como *"5.000m de cable fibra óptica SM G.652D 12 hilos de Corning a 1,60€/m"*, Orbita:

- **🔍 Encuentra el artículo en el catálogo** por similitud semántica (embeddings), entendiendo cantidad y unidad (metros vs bobina, etc.).
- **🧬 Resuelve duplicados** — detecta que el mismo producto está dado de alta con varios SKUs/proveedores/precios y los consolida en un único producto canónico (200 SKUs → 89 productos reales).
- **🏆 Recomienda el SKU ganador** dentro del grupo de duplicados con un score determinista: **contrato → precio → cuota → ESG**. No te hace elegir entre el ruido; decide por ti y muestra el ahorro.
- **📄 Consulta el contrato marco** vigente de la categoría y sus proveedores homologados (con la cuota actual de cada uno al pasar el ratón).
- **💰 Valida el precio** contra histórico + un modelo ML (XGBoost): ¿es precio justo? ¿hay descuento por volumen? Si está por encima del negociado → *aprobar con condiciones*.
- **⚖️ Comprueba la cuota** del comprador con cada proveedor candidato (market share YTD vs objetivo del contrato).
- **🌱 Evalúa el ESG** del proveedor (0-100, breakdown carbono/social/gobernanza, certificaciones) y alerta si es bajo.
- **🚩 Detecta maverick spend** — si el artículo no está en catálogo homologado, lo rechaza con alerta.
- **✅ Emite un veredicto** final: **APROBAR / APROBAR CON CONDICIONES / RECHAZAR**, con justificación y alertas.

> La detección de duplicados y el score del ganador son **deterministas** (reglas, no el LLM). El modelo de lenguaje solo orquesta y redacta; los números son reproducibles y defendibles.

## 🏗️ Arquitectura

Ver `ARCHITECTURE.md` para diagrama y descripción detallada. Las firmas exactas de las 6 tools están en `TOOLS_SPEC.md`.

## 🛠️ Stack tecnológico

- **LLM**: Ollama Cloud (Mistral o Llama) — endpoint y modelo en `.env`
- **Agente**: LangGraph + LangChain (grafo ReAct)
- **Embeddings**: sentence-transformers (local)
- **ML**: XGBoost (price_benchmark)
- **API**: FastAPI con streaming SSE (`api/server.py`)
- **Frontend**: React servido por el propio FastAPI (`frontend/index.html`) + alternativa en Streamlit (`frontend/app.py`)
- **Datos**: CSVs + JSONs sintéticos

## 🚀 Quick start

```bash
# 1. Setup
python3.11 -m venv venv
source venv/bin/activate
pip install -e .

# 2. Configurar credenciales del LLM: crea un .env en la raíz con
#   OLLAMA_CLOUD_ENDPOINT=https://...
#   OLLAMA_CLOUD_MODEL=mistral
#   OLLAMA_CLOUD_API_KEY=...

# 3. Generar datos (incluye la canonicalización del catálogo)
jupyter notebook notebooks/01_generate_synthetic_data.ipynb
# o, si ya hay datos, solo (re)canonicalizar el catálogo:
python scripts/build_canonical_ids.py
```

### Arrancar la app (recomendado: FastAPI + frontend React)

El servidor FastAPI sirve **a la vez** la API y el frontend React, en el mismo puerto:

```bash
uvicorn api.server:app --reload --port 8000
```

Abre **http://localhost:8000** en el navegador. El frontend usa `window.location.origin`, así que no hay que configurar URLs.

- `GET /health` — estado del servicio y modelo activo
- `POST /api/chat` — análisis del agente en streaming (Server-Sent Events)

### Alternativa: interfaz Streamlit

```bash
streamlit run frontend/app.py        # abre en http://localhost:8501
```

### Ejemplos de consulta

```
5.000m de cable fibra óptica SM G.652D 12 hilos de Corning a 1,60€/m para red troncal Madrid
200 ONTs Huawei EchoLife EG8145V5 GPON a 40€/u para despliegue FTTH Barcelona
5 unidades RRU Huawei AAU5613 5G NR 64T64R 3.5GHz a 16.500€/u para macro 5G
10.000m de cable fibra óptica SM G.652D 12 hilos Corning a 3,20€/m. ¿Lo apruebo?
Servicios de instalación FTTH en Galicia — 1,8M€
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
└── .env                    # credenciales del LLM (no versionado)
```

## 🧬 Resolución de duplicados

El catálogo tiene duplicados (mismo producto, distinto SKU/proveedor/precio). En vez de detectarlos en cada búsqueda, se resuelven **offline**: `scripts/build_canonical_ids.py` asigna un `canonical_id` a cada artículo (Tier 1 nombre exacto + Tier 2 matching semántico). `catalog_search` agrupa por ese id y `recommend_variant` elige el ganador del grupo (contrato → precio → cuota → ESG). Resultado: **200 SKUs → 89 productos reales**.

## 📖 Documentación

- `ARCHITECTURE.md`: Diagrama y descripción de la solución
- `TOOLS_SPEC.md`: Especificación exacta de las 6 tools