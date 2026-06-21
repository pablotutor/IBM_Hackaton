"""
Tool 1: catalog_search
Busca artículos en el catálogo usando embeddings + cosine similarity y los agrupa
por producto canónico (canonical_id), precalculado offline por
scripts/build_canonical_ids.py.

La duplicación es una propiedad DEL CATÁLOGO, no de cada búsqueda: cada artículo
ya trae su `canonical_id`. Aquí solo agrupamos los resultados por ese id y, dentro
de cada grupo, marcamos el ganador preliminar por precio. El agente afina luego el
ganador con contrato / precio justo / cuota / ESG.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools._shared import DATA_SYNTHETIC, embed, cosine_top_k

MIN_SIMILARITY_THRESHOLD = 0.60  # por debajo de este score el artículo se considera no encontrado

# Bonus de similitud cuando la unidad de medida del artículo coincide con la que
# implica la consulta (p.ej. "5.000m" → uom "metro"). Evita confundir un cable por
# metro con una bobina/unidad del mismo material.
UOM_MATCH_BONUS = 0.06

# Caché del índice — incluye los 200 items (canónicos + duplicados)
_CATALOG_INDEX: dict = {}


def _infer_uom(query: str) -> str | None:
    """Deduce la unidad de medida implícita en la consulta, o None si es ambigua."""
    import re as _re
    q = query.lower()
    # metro: "5.000m", "5000 metros", "/m", "km", o la palabra metro(s)
    if (_re.search(r'\d[\d.,]*\s*(?:m|metros?|km)\b', q) or '/m' in q
            or _re.search(r'\bmetros?\b', q)):
        return "metro"
    # unidad: "200 uds", "5 unidades", "/u", o la palabra unidad(es)
    if (_re.search(r'\d[\d.,]*\s*(?:u|uds?\.?|unidades?)\b', q) or '/u' in q
            or _re.search(r'\bunidades?\b', q)):
        return "unidad"
    return None


def _ensure_index() -> dict:
    if _CATALOG_INDEX:
        return _CATALOG_INDEX

    import pandas as pd

    df = pd.read_csv(DATA_SYNTHETIC / "catalog.csv")
    # Indexamos TODOS: canónicos y duplicados para que el agente los vea
    df_all = df.reset_index(drop=True)

    # Fallback: si el catálogo aún no está canonicalizado, cada SKU es su propio
    # producto (degradación elegante; ejecuta scripts/build_canonical_ids.py).
    if "canonical_id" not in df_all.columns:
        df_all["canonical_id"]   = df_all["sku"]
        df_all["canonical_name"] = df_all["name"]

    docs = (df_all["name"] + ". " + df_all["description"]).tolist()
    vecs = embed(docs)

    # Mapa canonical_id -> todas sus variantes (para grupos completos, no solo top-k)
    variants_by_canonical: dict[str, list[dict]] = {}
    for _, row in df_all.iterrows():
        variants_by_canonical.setdefault(str(row["canonical_id"]), []).append({
            "sku":            str(row["sku"]),
            "name":           str(row["name"]),
            "supplier":       str(row["supplier"]),
            "unit_price_eur": float(row["unit_price_eur"]),
            "uom":            str(row["uom"]),
            "is_duplicate":   bool(row["is_duplicate"]),
        })

    _CATALOG_INDEX.update({
        "df": df_all,
        "vecs": vecs,
        "variants_by_canonical": variants_by_canonical,
    })
    return _CATALOG_INDEX


class CatalogSearchInput(BaseModel):
    description: str = Field(..., description="Descripción del artículo a buscar")
    limit: int       = Field(5, ge=1, le=20, description="Máximo de resultados")


@tool(args_schema=CatalogSearchInput)
def catalog_search(description: str, limit: int = 5) -> dict:
    """
    Busca artículos en el catálogo de compras que coincidan semánticamente con
    la descripción dada y los agrupa por producto canónico: si el mismo producto
    está dado de alta varias veces (distinto SKU/proveedor/precio), aparece como
    un único grupo con sus variantes y el ganador preliminar por precio, para
    evitar compras redundantes. Úsala siempre que el usuario mencione un artículo
    o material que quiere comprar.
    """
    try:
        idx = _ensure_index()
        df   = idx["df"]
        vecs = idx["vecs"]
        variants_by_canonical = idx["variants_by_canonical"]

        q_vec = embed([description])[0]
        top_idx, scores = cosine_top_k(q_vec, vecs, min(limit, len(df)))

        results = []
        for i, score in zip(top_idx, scores):
            row = df.iloc[i]
            results.append({
                "sku":              str(row["sku"]),
                "name":             str(row["name"]),
                "description":      str(row["description"]),
                "category":         str(row["category"]),
                "unit_price_eur":   float(row["unit_price_eur"]),
                "supplier":         str(row["supplier"]),
                "uom":              str(row["uom"]),
                "similarity_score": round(float(score), 4),
                "is_duplicate":     bool(row["is_duplicate"]),
                "canonical_id":     str(row["canonical_id"]),
                "canonical_name":   str(row["canonical_name"]),
            })

        # Re-ranking: bonus por tokens numéricos del query (discriminan "12 hilos" vs "96 hilos")
        import re as _re
        num_tokens = _re.findall(r'\b\d+\b', description)
        if num_tokens:
            for r in results:
                text = r["name"] + " " + r["description"]
                bonus = sum(0.02 for tok in num_tokens if _re.search(rf'\b{tok}\b', text))
                r["similarity_score"] = round(r["similarity_score"] + bonus, 4)

        # Re-ranking por unidad de medida: si la consulta implica una uom (metro/unidad),
        # premia los artículos con esa uom (evita p.ej. recomendar una bobina para metros).
        wanted_uom = _infer_uom(description)
        if wanted_uom:
            for r in results:
                if r["uom"] == wanted_uom:
                    r["similarity_score"] = round(r["similarity_score"] + UOM_MATCH_BONUS, 4)

        results.sort(key=lambda r: r["similarity_score"], reverse=True)

        # Si el mejor match tiene score muy bajo, el artículo no está en catálogo
        if not results or results[0]["similarity_score"] < MIN_SIMILARITY_THRESHOLD:
            return {
                "status":  "not_found",
                "query":   description,
                "message": f"Artículo no encontrado en catálogo (mejor similitud: {results[0]['similarity_score'] if results else 0:.4f}, umbral mínimo: {MIN_SIMILARITY_THRESHOLD}). El artículo solicitado no existe en el catálogo homologado — se trata de un posible maverick spend.",
                "results": [],
                "groups": [],
                "total_found": 0,
                "duplicate_groups_detected": 0,
                "duplicates_detected": 0,
                "duplicate_warning": None,
            }

        # ── Agrupación por producto canónico ──────────────────────────────────
        # Recorremos los resultados en orden de similitud y, por cada canonical_id
        # nuevo, traemos TODAS sus variantes del catálogo (no solo las que cayeron
        # en el top-k) para que el grupo esté completo.
        groups = []
        seen_canonical = set()
        for r in results:
            cid = r["canonical_id"]
            if cid in seen_canonical:
                continue
            seen_canonical.add(cid)

            variants = sorted(
                variants_by_canonical.get(cid, []),
                key=lambda v: v["unit_price_eur"],
            )
            for k, v in enumerate(variants):
                v["preliminary_best"] = (k == 0)  # más barato (refina el agente)

            prices = [v["unit_price_eur"] for v in variants]
            p_min, p_max = min(prices), max(prices)
            overspend = round(100 * (p_max - p_min) / p_min, 1) if p_min > 0 else 0.0

            groups.append({
                "group_id":                f"grp_{len(groups) + 1}",
                "canonical_id":            cid,
                "canonical_name":          r["canonical_name"],
                "category":                r["category"],
                "uom":                     r["uom"],
                "best_similarity_score":   r["similarity_score"],
                "variant_count":           len(variants),
                "price_range_eur":         {"min": p_min, "max": p_max},
                "potential_overspend_pct": overspend,
                "variants":                variants,
            })

        # Métricas de duplicación (robustas: derivadas del canonical_id, no de umbrales)
        dup_groups = [g for g in groups if g["variant_count"] > 1]
        duplicate_groups_detected = len(dup_groups)
        duplicates_detected = sum(g["variant_count"] - 1 for g in dup_groups)

        duplicate_warning = None
        if dup_groups:
            parts = [
                f"{g['canonical_name']}: {g['variant_count']} variantes "
                f"({g['price_range_eur']['min']:.2f}–{g['price_range_eur']['max']:.2f}€"
                f", hasta {g['potential_overspend_pct']:.0f}% sobrecoste)"
                for g in dup_groups
            ]
            duplicate_warning = (
                f"⚠️ {duplicate_groups_detected} grupo(s) de duplicados "
                f"({duplicates_detected} variantes redundantes): " + " | ".join(parts)
            )

        return {
            "status":                    "success",
            "query":                     description,
            "results":                   results,
            "groups":                    groups,
            "total_found":               len(results),
            "duplicate_groups_detected": duplicate_groups_detected,
            "duplicates_detected":       duplicates_detected,
            "duplicate_warning":         duplicate_warning,
        }

    except FileNotFoundError:
        return {"status": "error", "message": "Catálogo no encontrado. Ejecuta el notebook de datos primero."}
    except Exception as e:
        return {"status": "error", "message": f"Error en catalog_search: {str(e)}"}
