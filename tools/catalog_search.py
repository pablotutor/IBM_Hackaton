"""
Tool 1: catalog_search
Busca artículos similares en el catálogo usando embeddings + cosine similarity.
Detecta duplicados semánticos: artículos distintos que describen el mismo producto.
"""
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools._shared import DATA_SYNTHETIC, embed, cosine_top_k

# Umbral para considerar dos resultados duplicados entre sí
PAIRWISE_DUP_THRESHOLD = 0.75

# Caché del índice — incluye los 200 items (canónicos + duplicados)
_CATALOG_INDEX: dict = {}


def _ensure_index() -> dict:
    if _CATALOG_INDEX:
        return _CATALOG_INDEX

    import pandas as pd

    df = pd.read_csv(DATA_SYNTHETIC / "catalog.csv")
    # Indexamos TODOS: canónicos y duplicados para que el agente los vea
    df_all = df.reset_index(drop=True)

    docs = (df_all["name"] + ". " + df_all["description"]).tolist()
    vecs = embed(docs)

    _CATALOG_INDEX.update({"df": df_all, "vecs": vecs})
    return _CATALOG_INDEX


class CatalogSearchInput(BaseModel):
    description: str = Field(..., description="Descripción del artículo a buscar")
    limit: int       = Field(5, ge=1, le=20, description="Máximo de resultados")


@tool(args_schema=CatalogSearchInput)
def catalog_search(description: str, limit: int = 5) -> dict:
    """
    Busca artículos en el catálogo de compras que coincidan semánticamente con
    la descripción dada. Detecta si hay duplicados (el mismo artículo con
    distintos nombres) para evitar compras redundantes. Úsala siempre que el
    usuario mencione un artículo o material que quiere comprar.
    """
    try:
        idx = _ensure_index()
        df   = idx["df"]
        vecs = idx["vecs"]

        q_vec = embed([description])[0]
        top_idx, scores = cosine_top_k(q_vec, vecs, min(limit, len(df)))

        results = []
        result_vecs = []
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
            })
            result_vecs.append(vecs[i])

        # Detección de duplicados: comparación cruzada entre todos los resultados
        # Dos items son duplicados si su similitud entre sí supera el umbral
        import numpy as np
        dup_groups = []   # lista de sets con SKUs que son duplicados entre sí
        flagged = set()

        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                sim_ij = float(np.dot(result_vecs[i], result_vecs[j]))
                if sim_ij >= PAIRWISE_DUP_THRESHOLD:
                    # Buscar si alguno ya pertenece a un grupo
                    merged = False
                    for g in dup_groups:
                        if results[i]["sku"] in g or results[j]["sku"] in g:
                            g.add(results[i]["sku"])
                            g.add(results[j]["sku"])
                            merged = True
                            break
                    if not merged:
                        dup_groups.append({results[i]["sku"], results[j]["sku"]})
                    flagged.update([results[i]["sku"], results[j]["sku"]])

        duplicates_detected = len(flagged)
        duplicate_warning = None
        if dup_groups:
            group_strs = []
            for g in dup_groups:
                skus = sorted(g)
                names = [r["name"] for r in results if r["sku"] in g]
                group_strs.append(" ≈ ".join(f"{s} ({n})" for s, n in zip(skus, names)))
            duplicate_warning = (
                f"⚠️ {duplicates_detected} artículos duplicados detectados en catálogo "
                f"(similitud ≥ {PAIRWISE_DUP_THRESHOLD:.0%}): " + " | ".join(group_strs)
            )

        return {
            "status":              "success",
            "query":               description,
            "results":             results,
            "total_found":         len(results),
            "duplicates_detected": duplicates_detected,
            "duplicate_warning":   duplicate_warning,
        }

    except FileNotFoundError:
        return {"status": "error", "message": "Catálogo no encontrado. Ejecuta el notebook de datos primero."}
    except Exception as e:
        return {"status": "error", "message": f"Error en catalog_search: {str(e)}"}
