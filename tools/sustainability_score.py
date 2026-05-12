"""
Tool 5: sustainability_score
Consulta el score ESG de un proveedor usando RAG sobre la BD sintética de ESG.
En producción se conectaría a EcoVadis API o MSCI ESG.
"""
import json
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional

from tools._shared import DATA_SYNTHETIC, embed, cosine_top_k

ESG_SCORE_ALERT_THRESHOLD = 50   # score < 50 → alerta ESG

_ESG_INDEX: dict = {}


def _ensure_index() -> dict:
    if _ESG_INDEX:
        return _ESG_INDEX

    esg_path = DATA_SYNTHETIC / "esg_scores.json"
    with open(esg_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    # Texto de búsqueda: nombre + categorías + notas de certificaciones
    docs = []
    for r in records:
        cats = " ".join(r.get("categories", []))
        text = f"{r['supplier']}. Categorías: {cats}. {r.get('certifications_notes', '')}"
        docs.append(text)

    vecs = embed(docs)
    _ESG_INDEX.update({"records": records, "docs": docs, "vecs": vecs})
    return _ESG_INDEX


class SustainabilityScoreInput(BaseModel):
    supplier: str = Field(..., description="Nombre del proveedor a evaluar")
    category: Optional[str] = Field(None, description="Categoría del producto (opcional, mejora la búsqueda)")


@tool(args_schema=SustainabilityScoreInput)
def sustainability_score(supplier: str, category: Optional[str] = None) -> dict:
    """
    Consulta el score ESG (medioambiental, social y de gobernanza) de un proveedor.
    Devuelve puntuación 0-100, breakdown por dimensión (carbono, social, gobernanza)
    y certificaciones presentes o ausentes (ISO 14001, CDP Score, Science Based Targets,
    EcoVadis rating). Úsala siempre que el usuario pregunte por sostenibilidad, ESG,
    impacto medioambiental o cuando necesites comparar proveedores por criterios ESG.
    """
    try:
        idx = _ensure_index()
        records = idx["records"]
        vecs    = idx["vecs"]

        query = supplier
        if category:
            query = f"{supplier} {category}"

        # Primero intentar match exacto por nombre (insensible a mayúsculas)
        supplier_lower = supplier.strip().lower()
        exact_i = next(
            (i for i, r in enumerate(records) if r["supplier"].lower() == supplier_lower),
            None,
        )

        if exact_i is not None:
            best_i     = exact_i
            best_score = 1.0
            # Top alternativas: otros proveedores con categorías solapadas
            candidate_cats = set(records[exact_i].get("categories", []))
            alts_raw = [
                (i, r) for i, r in enumerate(records)
                if i != exact_i and set(r.get("categories", [])) & candidate_cats
            ]
            alts_raw.sort(key=lambda x: x[1]["esg_score"], reverse=True)
            alternatives = [
                {"supplier": r["supplier"], "esg_score": r["esg_score"]}
                for _, r in alts_raw[:3]
            ]
        else:
            # Fallback: búsqueda semántica por embeddings
            q_vec = embed([query])[0]
            top_idx, scores = cosine_top_k(q_vec, vecs, k=min(4, len(records)))
            best_i     = top_idx[0]
            best_score = float(scores[0])
            alternatives = []
            for i in top_idx[1:]:
                if float(scores[list(top_idx).index(i)]) > 0.2:
                    alternatives.append({
                        "supplier":  records[i]["supplier"],
                        "esg_score": records[i]["esg_score"],
                    })

        if best_score < 0.3:
            # Sin coincidencia suficiente — devolver sugerencias
            suggestions = [records[i]["supplier"] for i in top_idx[:3]]
            return {
                "status":      "not_found",
                "message":     f"No se encontró proveedor ESG para '{supplier}'. Proveedores similares: {suggestions}",
                "suggestions": suggestions,
            }

        r = records[best_i]

        # Formatear certificaciones con iconos para la UI
        cdp     = r.get("cdp_score", "N/D")
        iso     = r.get("iso_14001", False)
        sbt     = r.get("science_based_targets", False)
        eco_rat = r.get("ecovadis_rating", "N/D")
        eco_sc  = r.get("ecovadis_score")
        nzy     = r.get("net_zero_target_year")
        renew   = r.get("renewable_energy_pct", 0)

        certifications = {
            "iso_14001":              iso,
            "iso_14001_label":        "✅ ISO 14001" if iso else "❌ ISO 14001 (ausente)",
            "cdp_score":              cdp,
            "cdp_score_label":        f"CDP Score {cdp}",
            "science_based_targets":  sbt,
            "sbt_label":              "✅ Science Based Targets (SBTi)" if sbt else "❌ Science Based Targets (no adherido)",
            "ecovadis_rating":        eco_rat,
            "ecovadis_score":         eco_sc,
            "ecovadis_label":         f"EcoVadis {eco_rat}" + (f" ({eco_sc}/100)" if eco_sc else ""),
        }

        esg_total = r["esg_score"]
        alert = esg_total < ESG_SCORE_ALERT_THRESHOLD

        return {
            "status":              "success",
            "supplier":            r["supplier"],
            "similarity_score":    round(best_score, 4),
            "esg_score":           esg_total,
            "esg_alert":           alert,
            "esg_alert_message":   f"⚠️ Score ESG bajo ({esg_total}/100): revisar criterios de sostenibilidad antes de adjudicar." if alert else None,
            "breakdown": {
                "carbon_score":     r.get("carbon_score"),
                "social_score":     r.get("social_score"),
                "governance_score": r.get("governance_score"),
            },
            "certifications":        certifications,
            "net_zero_target_year":  nzy,
            "renewable_energy_pct":  renew,
            "notes":                 r.get("certifications_notes", ""),
            "top_alternatives":      alternatives,
        }

    except FileNotFoundError:
        return {"status": "error", "message": "BD ESG no encontrada. Verifica data/synthetic/esg_scores.json."}
    except Exception as e:
        return {"status": "error", "message": f"Error en sustainability_score: {str(e)}"}
