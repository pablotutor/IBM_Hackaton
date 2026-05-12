"""
Tool 5: sustainability_score
Consulta el score ESG de un proveedor mediante query directa a la BD estructurada.
Los datos ESG son numéricos y booleanos — no requieren RAG.
En producción se conectaría a EcoVadis API o MSCI ESG.
"""
import json
import pandas as pd
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Optional

from tools._shared import DATA_SYNTHETIC

ESG_SCORE_ALERT_THRESHOLD = 50

_ESG_DF: Optional[pd.DataFrame] = None


def _get_df() -> pd.DataFrame:
    global _ESG_DF
    if _ESG_DF is None:
        path = DATA_SYNTHETIC / "esg_scores.json"
        with open(path, "r", encoding="utf-8") as f:
            _ESG_DF = pd.DataFrame(json.load(f))
    return _ESG_DF


class SustainabilityScoreInput(BaseModel):
    supplier: str = Field(..., description="Nombre del proveedor a evaluar")
    category: Optional[str] = Field(None, description="Categoría del producto (opcional, filtra alternativas)")


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
        df = _get_df()

        # Query exacta insensible a mayúsculas
        mask = df["supplier"].str.lower() == supplier.strip().lower()
        matches = df[mask]

        if matches.empty:
            # Devolver lista de proveedores disponibles como ayuda
            available = df["supplier"].tolist()
            return {
                "status":    "not_found",
                "message":   f"Proveedor '{supplier}' no encontrado en la BD ESG.",
                "available": available,
            }

        r = matches.iloc[0]

        iso     = bool(r["iso_14001"])
        sbt     = bool(r["science_based_targets"])
        cdp     = str(r["cdp_score"])
        eco_rat = str(r["ecovadis_rating"])
        eco_sc  = int(r["ecovadis_score"]) if pd.notna(r["ecovadis_score"]) else None
        nzy     = int(r["net_zero_target_year"]) if pd.notna(r["net_zero_target_year"]) else None
        renew   = int(r["renewable_energy_pct"])
        esg_total = int(r["esg_score"])
        alert   = esg_total < ESG_SCORE_ALERT_THRESHOLD

        certifications = {
            "iso_14001":             iso,
            "iso_14001_label":       "✅ ISO 14001" if iso else "❌ ISO 14001 (ausente)",
            "cdp_score":             cdp,
            "science_based_targets": sbt,
            "sbt_label":             "✅ Science Based Targets (SBTi)" if sbt else "❌ Science Based Targets (no adherido)",
            "ecovadis_rating":       eco_rat,
            "ecovadis_score":        eco_sc,
            "ecovadis_label":        f"EcoVadis {eco_rat}" + (f" ({eco_sc}/100)" if eco_sc else ""),
        }

        # Alternativas: otros proveedores con categorías solapadas, ordenados por ESG desc
        supplier_cats = set(r["categories"])
        alt_mask = df["supplier"].str.lower() != supplier.strip().lower()
        if category:
            alt_mask &= df["categories"].apply(lambda cats: category in cats)
        else:
            alt_mask &= df["categories"].apply(lambda cats: bool(set(cats) & supplier_cats))

        alternatives = (
            df[alt_mask][["supplier", "esg_score"]]
            .sort_values("esg_score", ascending=False)
            .head(3)
            .to_dict(orient="records")
        )

        return {
            "status":             "success",
            "supplier":           str(r["supplier"]),
            "esg_score":          esg_total,
            "esg_alert":          alert,
            "esg_alert_message":  f"⚠️ Score ESG bajo ({esg_total}/100): revisar criterios de sostenibilidad antes de adjudicar." if alert else None,
            "breakdown": {
                "carbon_score":     int(r["carbon_score"]),
                "social_score":     int(r["social_score"]),
                "governance_score": int(r["governance_score"]),
            },
            "certifications":       certifications,
            "net_zero_target_year": nzy,
            "renewable_energy_pct": renew,
            "notes":                str(r["certifications_notes"]),
            "top_alternatives":     alternatives,
        }

    except FileNotFoundError:
        return {"status": "error", "message": "BD ESG no encontrada. Verifica data/synthetic/esg_scores.json."}
    except Exception as e:
        return {"status": "error", "message": f"Error en sustainability_score: {str(e)}"}
