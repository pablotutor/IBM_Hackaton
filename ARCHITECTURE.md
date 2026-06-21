# Arquitectura del Sistema

## 🏗️ Visión general
```
┌─────────────────────────────────────────────────┐
│         Frontend (Streamlit)                    │
│      Chat + Panel de razonamiento               │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│            Agente LangGraph                     │
│       Orquesta tools y razonamientos            │
└──────────────────┬──────────────────────────────┘
                   │
┌──────┬──────┬──────┬──────┬──────┬─────────────┐
│      │      │      │      │      │             │
▼      ▼      ▼      ▼      ▼      ▼             │
┌──────┐┌──────┐┌──────┐┌──────┐┌──────────────┐┌──────────────┐
│catalog││contr.││quota_││price_││sustainability││ recommend_   │
│_search││lookup││status││bench.││ _score       ││ variant      │
│(RAG+  ││(RAG) ││(SQL) ││(ML)  ││(SQL)         ││(scoring det.)│
│canon.)│└──────┘└──────┘└──────┘└──────────────┘└──────────────┘
└──────┘                                          └──────────────┘
   ▲      recommend_variant orquesta contract/quota/price/esg ──┘
   │
┌──┴──────────────┐
│ canonical_id    │  ← scripts/build_canonical_ids.py (offline)
│ (catalog.csv)   │
└─────────────────┘
   │            │
   ▼            ▼
┌─────────────────┐         ┌──────────────────┐
│ Datos sintéticos│         │ Ollama Cloud     │
│ (CSVs + JSONs)  │         │ (LLM)            │
└─────────────────┘         └──────────────────┘
```

## 📊 Flujo de una consulta

1. Usuario escribe solicitud de compra
2. Agente recibe la solicitud
3. **Ronda 1** (paralelo): `catalog_search` + `contract_lookup`
4. **Ronda 2** (paralelo): `price_benchmark` + `quota_status` + `sustainability_score`; y si hay duplicados (`duplicate_groups_detected > 0`), `recommend_variant` con el `canonical_id`
5. Recibe resultados y razona
6. Genera recomendación final con el `winner` de recommend_variant, justificación, ahorro e impacto ESG
7. Frontend muestra el razonamiento paso a paso

## 🔧 Las 6 Tools

### catalog_search
- Busca artículos similares en catálogo (RAG con embeddings)
- **Agrupa por `canonical_id`**: las variantes del mismo producto se devuelven como un único grupo (`groups`) con su ganador preliminar por precio
- La detección de duplicados NO se hace en caliente: el `canonical_id` está precalculado offline

### contract_lookup
- Recupera contratos marco vigentes
- Extrae términos y condiciones
- RAG sobre PDFs de contratos

### quota_status
- Consulta cumplimiento de cuota acumulado
- Compara vs objetivo
- Query a base de datos de transacciones

### price_benchmark
- Estima precio justo
- Usa histórico + modelo ML
- Aplica descuentos por volumen

### sustainability_score
- Consulta score ESG del proveedor (0-100)
- Breakdown por carbono, social y gobernanza
- Certificaciones: ISO 14001, CDP Score, SBTi, EcoVadis
- Query SQL directa sobre `esg_scores.json` (datos estructurados)
- En producción: conectable a EcoVadis API o MSCI ESG

### recommend_variant
- Decide el **ganador** dentro de un grupo de duplicados (mismo `canonical_id`)
- Orquesta contract_lookup / price_benchmark / quota_status / sustainability_score por variante
- Calcula un `recommendation_score` (0-100) **determinista** (no lo calcula el LLM):
  `100·(0.40·contrato + 0.35·precio + 0.15·cuota + 0.10·esg) − 40·esg_alert`
- Jerarquía **contrato primero**; el precio es baratura relativa en el grupo; la cuota es desempate
- Devuelve `winner`, `ranking`, `why` y `savings_vs_worst_pct`

## 🧬 Canonicalización del catálogo (resolución de duplicados)

`scripts/build_canonical_ids.py` (offline, también ejecutado en el notebook) asigna a cada artículo un `canonical_id`/`canonical_name`:
- **Tier 1 (exacto):** agrupa por nombre normalizado → ~90% del catálogo, determinista
- **Tier 2 (semántico):** los `*-DUP-*` parafraseados se enganchan a su canónico por embedding, bloqueando por `category`+`uom`

Así la duplicación es propiedad del catálogo (no de cada query): **200 SKUs → 89 productos reales**.

## 💾 Datos

- **catalog.csv**: 200 artículos = 89 productos reales (111 variantes redundantes); columnas `canonical_id`/`canonical_name`
- **contracts.json**: 5 contratos marco
- **transactions.csv**: 2000 transacciones históricas
- **forecast.csv**: Forecast mensual por categoría
- **contracts/**: TXT de contratos (para RAG)
- **esg_scores.json**: Scores ESG de 27 proveedores Telco

## 🔌 Integraciones

- **Ollama Cloud**: LLM remoto
- **ChromaDB**: Vector store local
- **LangSmith**: Observabilidad (opcional)