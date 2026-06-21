# Especificación de Tools — SmartProc Copilot

Todos los miembros del equipo deben conocer estas firmas **exactas** antes de codear.

> **v2**: añadida Tool 5 `sustainability_score`. Criterio de selección de técnica: RAG para datos no estructurados (documentos, descripciones libres); SQL/pandas para datos estructurados (scores, booleanos, fechas).

## Tool 1: catalog_search

**Descripción:** Busca artículos en el catálogo que coincidan con la descripción del usuario y **los agrupa por producto canónico**. La detección de duplicados NO se hace en caliente: cada artículo trae un `canonical_id` precalculado offline por `scripts/build_canonical_ids.py` (Tier 1 nombre exacto + Tier 2 matching semántico para parafraseados). La tool solo agrupa por ese id y marca el ganador preliminar por precio; el agente afina el ganador con contrato/precio justo/cuota/ESG.

**Parámetros de entrada:**
- `description` (str, requerido): Descripción del artículo (ej: "fibra óptica monomodo")
- `limit` (int, opcional, default=5): Número máximo de resultados

**Output esperado (dict):**
```python
{
    "status": "success",
    "query": "cable drop ftth",
    # Lista plana de matches (compat. con frontend/agente). Cada item lleva canonical_id/name.
    "results": [
        {
            "sku": "EXT-007",
            "name": "Cable FO SM G.657A2 2 hilos drop FTTH",
            "description": "Cable drop FTTH monomodo...",
            "category": "fibra_optica",
            "unit_price_eur": 0.38,
            "supplier": "Prysmian",
            "uom": "metro",
            "similarity_score": 0.93,
            "is_duplicate": False,
            "canonical_id": "CAN-0001",
            "canonical_name": "Cable FO SM G.657A2 2 hilos drop FTTH"
        }
    ],
    # Resultados agrupados por producto canónico — lo que mueve la recomendación.
    "groups": [
        {
            "group_id": "grp_1",
            "canonical_id": "CAN-0001",
            "canonical_name": "Cable FO SM G.657A2 2 hilos drop FTTH",
            "category": "fibra_optica",
            "uom": "metro",
            "best_similarity_score": 0.93,
            "variant_count": 3,
            "price_range_eur": {"min": 0.38, "max": 0.50},
            "potential_overspend_pct": 31.6,        # (max-min)/min — el gancho de la demo
            "variants": [                            # ordenadas por precio asc
                {"sku": "EXT-007",    "supplier": "Prysmian", "unit_price_eur": 0.38, "uom": "metro", "is_duplicate": False, "preliminary_best": True},
                {"sku": "FO-007",     "supplier": "Prysmian", "unit_price_eur": 0.42, "uom": "metro", "is_duplicate": False, "preliminary_best": False},
                {"sku": "FO-DUP-003", "supplier": "Corning",  "unit_price_eur": 0.50, "uom": "metro", "is_duplicate": True,  "preliminary_best": False}
            ]
        }
    ],
    "total_found": 3,
    "duplicate_groups_detected": 1,                  # grupos con >1 variante
    "duplicates_detected": 2,                         # variantes redundantes (Σ variant_count-1)
    "duplicate_warning": "⚠️ 1 grupo(s) de duplicados (2 variantes redundantes): ..."
}
```

**`not_found`** (mejor similitud < 0.60 → posible maverick spend):
```python
{"status": "not_found", "query": "...", "message": "...", "results": [], "groups": [],
 "total_found": 0, "duplicate_groups_detected": 0, "duplicates_detected": 0, "duplicate_warning": None}
```

**Errors:**
```python
{"status": "error", "message": "No results found"}
```

> **Ganador final → Tool 6 `recommend_variant`** (determinista, no lo calcula el LLM).
> `preliminary_best` de catalog_search es solo el más barato; el ganador oficial lo
> decide `recommend_variant`.

---

## Tool 6: recommend_variant

**Descripción:** Decide QUÉ variante comprar dentro de un grupo de duplicados (mismo `canonical_id`). Reúne contrato/precio/cuota/ESG por variante y calcula un `recommendation_score` (0-100) determinista. El agente la llama cuando `catalog_search` devuelve `duplicate_groups_detected > 0`.

**Parámetros:**
- `canonical_id` (str, requerido): id del grupo (de catalog_search)
- `buyer_id` (str, default "buyer_mad_001"): para evaluar cuota
- `quantity` (int, default 1): para el benchmark de precio

**Scoring (jerarquía contrato primero):**
```
score = 100 · (0.40·contrato + 0.35·precio + 0.15·cuota + 0.10·esg) − 40·esg_alert
  contrato : 1.0 bajo contrato marco, 0.4 fuera (anti maverick spend)
  precio   : baratura RELATIVA en el grupo = min_precio_grupo / precio  (más barato = mejor)
  cuota    : under 1.0 · ok 0.85 · over 0.6  (desempate, no voltea el precio)
  esg      : esg_score/100 ; penalización −40 si esg_alert
```

**Output (dict):**
```python
{
    "status": "success",
    "canonical_id": "CAN-0001",
    "canonical_name": "Cable FO SM G.657A2 2 hilos drop FTTH",
    "category": "fibra_optica",
    "variant_count": 3,
    "winner": {
        "sku": "EXT-007", "supplier": "Prysmian", "unit_price_eur": 0.38,
        "recommendation_score": 91.0,
        "why": "bajo contrato 2024-CM-FO-001 · 12% bajo precio justo · cuota excedida · ESG 70"
    },
    "savings_vs_worst_pct": 24.0,
    "ranking": [ {"rank": 1, "recommended": True, "sku": "...", "recommendation_score": ..., "breakdown": {...}, "why": "..."}, ... ]
}
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
