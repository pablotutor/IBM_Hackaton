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
┌────────────┼────────────┬────────────┬────────────┐
│            │            │            │            │
▼            ▼            ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│ catalog_ │ │contract_ │ │ quota_   │ │ price_   │ │sustainability│
│ search   │ │ lookup   │ │ status   │ │benchmark │ │ _score       │
│(RAG)     │ │(RAG)     │ │(SQL)     │ │(ML)      │ │(SQL)         │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────────┘
│            │            │            │            │
└────────────┼────────────┴────────────┴────────────┘
│
┌────────────┴──────────────────┐
│                               │
▼                               ▼
┌─────────────────┐         ┌──────────────────┐
│ Datos sintéticos│         │ Ollama Cloud     │
│ (CSVs + JSONs)  │         │ (LLM)            │
└─────────────────┘         └──────────────────┘
```

## 📊 Flujo de una consulta

1. Usuario escribe solicitud de compra
2. Agente recibe la solicitud
3. Agente decide qué tools llamar (puede ser 1, 2, 3, 4 o 5)
4. Ejecuta tools en paralelo/secuencia según necesidad
5. Recibe resultados y razona
6. Genera recomendación final con justificación e impacto ESG
7. Frontend muestra el razonamiento paso a paso

## 🔧 Las 5 Tools

### catalog_search
- Busca artículos similares en catálogo
- Detecta duplicados semánticos
- Usa RAG con embeddings

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

## 💾 Datos

- **catalog.csv**: 200 artículos (con 20 duplicados intencionales)
- **contracts.json**: 5 contratos marco
- **transactions.csv**: 2000 transacciones históricas
- **forecast.csv**: Forecast mensual por categoría
- **contracts/**: TXT de contratos (para RAG)
- **esg_scores.json**: Scores ESG de 27 proveedores Telco

## 🔌 Integraciones

- **Ollama Cloud**: LLM remoto
- **ChromaDB**: Vector store local
- **LangSmith**: Observabilidad (opcional)