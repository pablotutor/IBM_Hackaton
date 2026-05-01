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
┌────────────┼────────────┬────────────┐
│            │            │            │
▼            ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ catalog_ │ │contract_ │ │ quota_   │ │ price_   │
│ search   │ │ lookup   │ │ status   │ │benchmark │
│(RAG)     │ │(RAG)     │ │(SQL)     │ │(ML)      │
└──────────┘ └──────────┘ └──────────┘ └──────────┘
│            │            │            │
└────────────┼────────────┴────────────┘
│
┌────────────┴──────────────────┐
│                               │
▼                               ▼
┌─────────────────┐         ┌──────────────────┐
│ Datos sintéticos│         │ Ollama Cloud     │
│ (CSVs + PDFs)   │         │ (LLM)            │
└─────────────────┘         └──────────────────┘
```

## 📊 Flujo de una consulta

1. Usuario escribe solicitud de compra
2. Agente recibe la solicitud
3. Agente decide qué tools llamar (puede ser 1, 2, 3 o 4)
4. Ejecuta tools en paralelo/secuencia según necesidad
5. Recibe resultados y razona
6. Genera recomendación final con justificación
7. Frontend muestra el razonamiento paso a paso

## 🔧 Las 4 Tools

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

## 💾 Datos

- **catalog.csv**: 200 artículos (con 20 duplicados intencionales)
- **contracts.json**: 5 contratos marco
- **transactions.csv**: 2000 transacciones históricas
- **forecast.csv**: Forecast mensual por categoría
- **contracts/**: PDFs/TXT de contratos (para RAG)

## 🔌 Integraciones

- **Ollama Cloud**: LLM remoto
- **ChromaDB**: Vector store local
- **LangSmith**: Observabilidad (opcional)