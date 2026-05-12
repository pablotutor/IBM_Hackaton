# Especificación de Tools — SmartProc Copilot

Todos los miembros del equipo deben conocer estas firmas **exactas** antes de codear.

> **v2**: añadida Tool 5 `sustainability_score`. Criterio de selección de técnica: RAG para datos no estructurados (documentos, descripciones libres); SQL/pandas para datos estructurados (scores, booleanos, fechas).

## Tool 1: catalog_search

**Descripción:** Busca artículos en el catálogo que coincidan con la descripción del usuario.

**Parámetros de entrada:**
- `description` (str, requerido): Descripción del artículo (ej: "fibra óptica monomodo")
- `limit` (int, opcional, default=5): Número máximo de resultados

**Output esperado (dict):**
```python
{
    "status": "success",
    "results": [
        {
            "sku": "SKU-1234",
            "name": "Cable FO SM 12 hilos",
            "description": "Fibra óptica monomodo...",
            "category": "fibra_óptica",
            "unit_price_eur": 2.50,
            "supplier": "Corning",
            "similarity_score": 0.95
        }
    ],
    "total_found": 3,
    "duplicates_detected": 2
}
```

**Errors:**
```python
{"status": "error", "message": "No results found"}
```

---

## Tool 2: contract_lookup

**Descripción:** Busca contratos marco vigentes para una categoría.

**Parámetros:**
- `category` (str, requerido): Categoría (ej: "fibra_óptica", "cables")

**Output:**
```python
{
    "status": "success",
    "contracts": [
        {
            "contract_id": "2024-CM-FO-001",
            "supplier": "Corning",
            "category": "fibra_óptica",
            "market_share_target": 0.60,
            "negotiated_price_eur": 2.15,
            "validity_start": "2024-01-01",
            "validity_end": "2025-12-31",
            "lead_time_days": 5,
            "key_terms": "Mínimo 1000m/mes..."
        }
    ]
}
```

---

## Tool 3: quota_status

**Descripción:** Estado del cumplimiento de cuota de un comprador.

**Parámetros:**
- `buyer_id` (str): ID del comprador (ej: "buyer_madrid_001")
- `supplier` (str): Nombre del proveedor (ej: "Corning")
- `category` (str): Categoría (ej: "fibra_óptica")

**Output:**
```python
{
    "status": "success",
    "buyer_id": "buyer_madrid_001",
    "supplier": "Corning",
    "category": "fibra_óptica",
    "ytd_spent_eur": 145000,
    "ytd_volume_units": 580000,
    "target_market_share": 0.60,
    "current_market_share": 0.72,
    "status_vs_target": "over",
    "recommendation": "Considera redirigir a Prysmian"
}
```

---

## Tool 4: price_benchmark

**Descripción:** Estima precio justo de un artículo.

**Parámetros:**
- `sku` (str): SKU del artículo
- `quantity` (int): Cantidad
- `supplier` (str, opcional): Proveedor si es conocido
- `target_delivery_days` (int, default=30): Plazo deseado

**Output:**
```python
{
    "status": "success",
    "sku": "SKU-1234",
    "quantity": 500,
    "historical_avg_price": 2.40,
    "current_market_range": {
        "min": 2.10,
        "max": 2.65,
        "median": 2.35
    },
    "estimated_fair_price": 2.20,
    "confidence": 0.92,
    "factors_considered": ["commodity_prices", "volume_discount", "lead_time"],
    "volume_discount_applicable": True,
    "discount_percentage": 5.0
}
```

---

---

## Tool 5: sustainability_score

**Descripción:** Consulta el score ESG de un proveedor. Técnica: query SQL directa sobre `esg_scores.json` (datos estructurados — no RAG). En producción: EcoVadis API o MSCI ESG.

**Parámetros:**
- `supplier` (str, requerido): Nombre del proveedor (ej: "Ericsson")
- `category` (str, opcional): Categoría del producto — filtra las alternativas sugeridas

**Output:**
```python
{
    "status": "success",
    "supplier": "Ericsson",
    "esg_score": 78,                  # 0-100
    "esg_alert": False,               # True si score < 50
    "esg_alert_message": None,        # texto de alerta o None
    "breakdown": {
        "carbon_score": 82,
        "social_score": 76,
        "governance_score": 74
    },
    "certifications": {
        "iso_14001": True,
        "iso_14001_label": "✅ ISO 14001",
        "cdp_score": "A-",
        "science_based_targets": True,
        "sbt_label": "✅ Science Based Targets (SBTi)",
        "ecovadis_rating": "Gold",
        "ecovadis_score": 71,
        "ecovadis_label": "EcoVadis Gold (71/100)"
    },
    "net_zero_target_year": 2040,
    "renewable_energy_pct": 68,
    "notes": "EcoVadis Gold pendiente de renovación en 2025. SBTi validado en 2022.",
    "top_alternatives": [
        {"supplier": "Nokia", "esg_score": 81},
        {"supplier": "Cisco", "esg_score": 76}
    ]
}
```

**Casos especiales:**
```python
# Proveedor no encontrado
{"status": "not_found", "message": "Proveedor 'X' no encontrado en la BD ESG.", "available": [...]}

# Error de sistema
{"status": "error", "message": "BD ESG no encontrada. Verifica data/synthetic/esg_scores.json."}
```

**Reglas de negocio aplicadas por el agente:**
- `esg_score < 50` → alerta ESG obligatoria en la respuesta
- Si dos proveedores tienen precio y cuota similares → recomendar el de mayor score ESG con justificación

---

## Notas de implementación

1. Todas las tools validan inputs con Pydantic
2. Timeout máximo: 5 segundos por tool
3. Errores siempre: `{"status": "error", "message": "..."}`
4. Las tools son idempotentes
5. Devuelven siempre dict (nunca excepciones sin capturar)
6. `quota_status`, `price_benchmark` y `sustainability_score` pueden llamarse en paralelo una vez conocidos categoría, SKU y proveedor
