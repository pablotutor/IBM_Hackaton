"""
Tool 6: recommend_variant
Decide el GANADOR dentro de un grupo de duplicados (mismo canonical_id).

La detección/agrupación de duplicados la hace catalog_search (offline + canonical_id).
Aquí resolvemos la pregunta de negocio: de las N variantes del mismo producto,
¿cuál comprar? Reúne las señales de las otras tools por variante y calcula un
`recommendation_score` (0-100) determinista, con jerarquía CONTRATO PRIMERO:

    score = 100 · (0.40·contrato + 0.35·precio_vs_justo + 0.15·cuota + 0.10·esg)
            − 40 si esg_alert

El scoring es determinista (no lo hace el LLM) para que la recomendación sea
reproducible y defendible. catalog_search se mantiene puro: esta tool es la que
orquesta contract_lookup / price_benchmark / quota_status / sustainability_score.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# Pesos de la jerarquía (contrato primero). Suman 1.0.
W_CONTRACT = 0.40
W_PRICE    = 0.35
W_QUOTA    = 0.15
W_ESG      = 0.10
ESG_ALERT_PENALTY = 40.0

# Factor de contrato: penaliza fuerte comprar fuera de contrato marco (maverick spend).
CONTRACT_OFF_FACTOR = 0.4

# Mapeo del estado de cuota a factor [0,1]. Rango ESTRECHO a propósito: la cuota
# es un desempate entre variantes de precio similar, no debe voltear una diferencia
# grande de precio (que pesa más en la jerarquía).
_QUOTA_FACTOR = {
    "under": 1.0,   # por debajo del objetivo: redirigir compra aquí ayuda
    "ok":    0.85,
    "on":    0.85,
    "near":  0.85,
    "over":  0.6,   # ya por encima del objetivo: comprar más empeora la cuota
}


def _price_factor(unit_price: float, min_group_price: float | None) -> float:
    """
    Baratura RELATIVA dentro del grupo de duplicados, en [0,1].
    Entre variantes del MISMO producto, más barato = mejor (la más barata = 1.0).
    No penalizamos 'por barato': sabemos que es el mismo artículo.
    """
    if not min_group_price or unit_price <= 0:
        return 1.0
    return max(0.0, min(1.0, min_group_price / unit_price))


def score_variant(signals: dict) -> dict:
    """
    Función pura de scoring. `signals` por variante:
        unit_price_eur (float), min_group_price (float|None), under_contract (bool),
        quota_status (str|None), esg_score (int|None), esg_alert (bool)
    Devuelve {score, breakdown}.
    """
    f_contract = 1.0 if signals.get("under_contract") else CONTRACT_OFF_FACTOR
    f_price    = _price_factor(signals["unit_price_eur"], signals.get("min_group_price"))
    f_quota    = _QUOTA_FACTOR.get(str(signals.get("quota_status") or "").lower(), 0.85)
    esg        = signals.get("esg_score")
    f_esg      = (esg / 100.0) if isinstance(esg, (int, float)) else 0.7

    raw = 100.0 * (W_CONTRACT * f_contract + W_PRICE * f_price + W_QUOTA * f_quota + W_ESG * f_esg)
    if signals.get("esg_alert"):
        raw -= ESG_ALERT_PENALTY

    score = round(max(0.0, min(100.0, raw)), 1)
    return {
        "score": score,
        "breakdown": {
            "contract": round(f_contract, 2),
            "price":    round(f_price, 2),
            "quota":    round(f_quota, 2),
            "esg":      round(f_esg, 2),
        },
    }


def _build_why(v: dict, signals: dict, contract_id: str | None) -> str:
    """Frase corta y legible de por qué esta variante puntúa como puntúa."""
    parts = []
    if signals.get("under_contract"):
        parts.append(f"bajo contrato {contract_id}" if contract_id else "bajo contrato marco")
    else:
        parts.append("⚠️ fuera de contrato")

    fair = signals.get("fair_price")
    if fair:
        diff = (v["unit_price_eur"] - fair) / fair
        if diff <= -0.03:
            parts.append(f"{abs(diff):.0%} bajo precio justo")
        elif diff >= 0.03:
            parts.append(f"{diff:.0%} sobre precio justo")
        else:
            parts.append("en precio justo")

    qs = str(signals.get("quota_status") or "").lower()
    if qs == "under":
        parts.append("cuota disponible")
    elif qs == "over":
        parts.append("cuota excedida")

    if signals.get("esg_alert"):
        parts.append(f"⚠️ ESG bajo ({signals.get('esg_score')})")
    elif isinstance(signals.get("esg_score"), (int, float)):
        parts.append(f"ESG {signals['esg_score']}")

    return " · ".join(parts)


class RecommendVariantInput(BaseModel):
    canonical_id: str = Field(..., description="canonical_id del grupo de duplicados (de catalog_search)")
    buyer_id: str     = Field("buyer_mad_001", description="ID del comprador (para evaluar cuota)")
    quantity: int     = Field(1, ge=1, description="Cantidad a comprar (para el benchmark de precio)")


@tool(args_schema=RecommendVariantInput)
def recommend_variant(canonical_id: str, buyer_id: str = "buyer_mad_001", quantity: int = 1) -> dict:
    """
    Recomienda QUÉ variante comprar dentro de un grupo de duplicados (mismo
    canonical_id devuelto por catalog_search). Calcula un recommendation_score
    determinista por variante combinando contrato (manda), precio vs. precio justo,
    cuota y ESG. Úsala cuando catalog_search detecte duplicate_groups_detected > 0,
    pasando el canonical_id del grupo a consolidar.
    """
    try:
        # Import diferido para no acoplar en tiempo de carga
        from tools.catalog_search import _ensure_index
        from tools.contract_lookup import contract_lookup
        from tools.price_benchmark import price_benchmark
        from tools.quota_status import quota_status
        from tools.sustainability_score import sustainability_score

        df = _ensure_index()["df"]
        grp = df[df["canonical_id"].astype(str) == str(canonical_id)]
        if grp.empty:
            return {"status": "not_found", "message": f"canonical_id '{canonical_id}' no encontrado."}

        category       = str(grp.iloc[0]["category"])
        canonical_name = str(grp.iloc[0]["canonical_name"])

        # ── Contrato: una sola llamada por categoría ──────────────────────────
        contract_suppliers: set[str] = set()
        contract_id: str | None = None
        contr = contract_lookup.func(category=category)
        if contr.get("status") == "success":
            for c in contr.get("contracts", []):
                contract_id = contract_id or c.get("contract_id")
                for s in c.get("suppliers", []):
                    contract_suppliers.add(str(s["name"]).lower())

        # ── Precio justo: del PRODUCTO, no de cada SKU duplicado ───────────────
        # Un solo benchmark sobre un representante (preferimos un SKU no-duplicado,
        # el más barato) y lo usamos como baremo común para todas las variantes.
        rep = grp[~grp["is_duplicate"].astype(bool)] if (~grp["is_duplicate"].astype(bool)).any() else grp
        rep_row = rep.sort_values("unit_price_eur").iloc[0]
        fair = None
        pb = price_benchmark.func(
            sku=str(rep_row["sku"]), quantity=quantity, supplier=str(rep_row["supplier"])
        )
        if pb.get("status") == "success":
            fair = pb.get("estimated_fair_price_eur")

        # ── Evaluar cada variante ─────────────────────────────────────────────
        min_group_price = float(grp["unit_price_eur"].min())
        ranked = []
        for _, row in grp.iterrows():
            sku      = str(row["sku"])
            supplier = str(row["supplier"])
            price    = float(row["unit_price_eur"])

            # Cuota
            qstatus = None
            q_current = None
            q_target = None
            qs = quota_status.func(buyer_id=buyer_id, supplier=supplier, category=category)
            if qs.get("status") == "success":
                qstatus = qs.get("status_vs_target")
                q_current = qs.get("current_share_pct")
                q_target = qs.get("target_share_pct")

            # ESG
            esg_score = None
            esg_alert = False
            esg = sustainability_score.func(supplier=supplier, category=category)
            if esg.get("status") == "success":
                esg_score = esg.get("esg_score")
                esg_alert = bool(esg.get("esg_alert"))

            under_contract = supplier.lower() in contract_suppliers
            signals = {
                "unit_price_eur":  price,
                "min_group_price": min_group_price,
                "under_contract":  under_contract,
                "fair_price":      fair,
                "quota_status":    qstatus,
                "esg_score":       esg_score,
                "esg_alert":       esg_alert,
            }
            scored = score_variant(signals)
            ranked.append({
                "sku":                  sku,
                "supplier":             supplier,
                "unit_price_eur":       price,
                "uom":                  str(row["uom"]),
                "recommendation_score": scored["score"],
                "breakdown":            scored["breakdown"],
                "under_contract":       under_contract,
                "fair_price_eur":       fair,
                "quota_status":         qstatus,
                "quota_current_pct":    q_current,
                "quota_target_pct":     q_target,
                "why":                  _build_why({"unit_price_eur": price}, signals, contract_id),
            })

        ranked.sort(key=lambda x: x["recommendation_score"], reverse=True)
        for k, v in enumerate(ranked):
            v["rank"] = k + 1
            v["recommended"] = (k == 0)

        winner = ranked[0]
        prices = [v["unit_price_eur"] for v in ranked]
        savings_pct = round(100 * (max(prices) - winner["unit_price_eur"]) / max(prices), 1) if max(prices) > 0 else 0.0

        # Comparativa de cuota de TODOS los proveedores candidatos (no solo el ganador):
        # permite ver el trade-off de redirigir compra entre proveedores. Deduplicado por proveedor.
        quota_comparison = []
        seen_suppliers = set()
        for v in ranked:
            if v["supplier"] in seen_suppliers:
                continue
            seen_suppliers.add(v["supplier"])
            quota_comparison.append({
                "supplier":        v["supplier"],
                "current_pct":     v["quota_current_pct"],
                "target_pct":      v["quota_target_pct"],
                "status_vs_target": v["quota_status"],
                "recommended":     v["recommended"],
            })

        return {
            "status":              "success",
            "canonical_id":        canonical_id,
            "canonical_name":      canonical_name,
            "category":            category,
            "variant_count":      len(ranked),
            "winner": {
                "sku":                  winner["sku"],
                "supplier":             winner["supplier"],
                "unit_price_eur":       winner["unit_price_eur"],
                "recommendation_score": winner["recommendation_score"],
                "why":                  winner["why"],
            },
            "savings_vs_worst_pct": savings_pct,
            "quota_comparison":     quota_comparison,
            "ranking":              ranked,
        }

    except Exception as e:
        return {"status": "error", "message": f"Error en recommend_variant: {str(e)}"}
