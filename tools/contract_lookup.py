"""
Tool 2: contract_lookup
Recupera contratos marco vigentes para una categoría.
Combina búsqueda exacta en contracts.json con RAG sobre los ficheros .txt.
"""
import json
from datetime import date
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools._shared import DATA_SYNTHETIC, embed, cosine_top_k

CATEGORY_ALIASES = {
    "fibra":          "fibra_optica",
    "fibra optica":   "fibra_optica",
    "fibra_óptica":   "fibra_optica",
    "ftth":           "fibra_optica",
    "radio":          "radio_acceso",
    "4g":             "radio_acceso",
    "5g":             "radio_acceso",
    "radio acceso":   "radio_acceso",
    "ont":            "equipos_red_acceso",
    "olt":            "equipos_red_acceso",
    "acceso":         "equipos_red_acceso",
    "red acceso":     "equipos_red_acceso",
    "servidores":     "servidores_it",
    "hardware":       "servidores_it",
    "it":             "servidores_it",
    "cpd":            "climatizacion_cpd",
    "climatizacion":  "climatizacion_cpd",
    "obra":           "obra_civil",
    "cobre":          "cables_cobre",
    "herramientas":   "herramientas_epi",
    "epi":            "herramientas_epi",
    "core":           "equipos_red_core",
}

# Caché del índice de contratos para RAG
_CONTRACTS_INDEX: dict = {}


def _normalize_category(category: str) -> str:
    key = category.lower().strip().replace("-", "_").replace("ó", "o").replace("á", "a")
    return CATEGORY_ALIASES.get(key, key)


def _ensure_contracts_index() -> dict:
    if _CONTRACTS_INDEX:
        return _CONTRACTS_INDEX

    contracts_dir = DATA_SYNTHETIC / "contracts"
    chunks, metas = [], []

    for txt_path in sorted(contracts_dir.glob("*.txt")):
        text = txt_path.read_text(encoding="utf-8")
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 40]
        for idx, chunk in enumerate(paragraphs):
            chunks.append(chunk)
            metas.append({"contract_id": txt_path.stem, "chunk": idx})

    vecs = embed(chunks)
    _CONTRACTS_INDEX.update({"chunks": chunks, "metas": metas, "vecs": vecs})
    return _CONTRACTS_INDEX


def _load_contracts() -> list:
    with open(DATA_SYNTHETIC / "contracts.json", encoding="utf-8") as f:
        return json.load(f)


def _is_valid(contract: dict) -> bool:
    today = date.today().isoformat()
    return contract["validity_start"] <= today <= contract["validity_end"]


class ContractLookupInput(BaseModel):
    category: str = Field(
        ...,
        description=(
            "Categoría del artículo. Valores: fibra_optica, radio_acceso, "
            "equipos_red_acceso, servidores_it, equipos_red_core, "
            "climatizacion_cpd, herramientas_epi, obra_civil, cables_cobre"
        ),
    )


@tool(args_schema=ContractLookupInput)
def contract_lookup(category: str) -> dict:
    """
    Recupera los contratos marco vigentes para una categoría de compra.
    Devuelve proveedores homologados, precios negociados, cuotas objetivo,
    descuentos por volumen y condiciones clave. Úsala para saber si hay un
    contrato activo antes de aprobar una compra y para conocer el proveedor
    y precio correcto.
    """
    try:
        cat_norm  = _normalize_category(category)
        contracts = _load_contracts()

        matching = [
            c for c in contracts
            if cat_norm in c.get("categories", []) and _is_valid(c)
        ]

        if not matching:
            expired = [
                c for c in contracts
                if cat_norm in c.get("categories", []) and not _is_valid(c)
            ]
            msg = f"No hay contratos vigentes para categoría '{cat_norm}'."
            if expired:
                msg += f" Contrato expirado: {expired[0]['contract_id']} (venció {expired[0]['validity_end']})."
            return {"status": "error", "message": msg}

        # RAG sobre textos de contrato para cláusulas relevantes
        try:
            idx = _ensure_contracts_index()
            query = f"condiciones {cat_norm} precio plazo entrega penalización descuento"
            q_vec = embed([query])[0]
            top_idx, _ = cosine_top_k(q_vec, idx["vecs"], 4)
            rag_snippets = [idx["chunks"][i] for i in top_idx]
        except Exception:
            rag_snippets = []

        contracts_out = []
        for c in matching:
            contracts_out.append({
                "contract_id":        c["contract_id"],
                "title":              c["title"],
                "category":           cat_norm,
                "suppliers": [
                    {
                        "name":                s["name"],
                        "market_share_target": s["market_share_target"],
                        "market_share_pct":    f"{s['market_share_target']*100:.0f}%",
                    }
                    for s in c.get("suppliers", [])
                ],
                "negotiated_prices":  c.get("negotiated_prices", {}),
                "validity_start":     c["validity_start"],
                "validity_end":       c["validity_end"],
                "lead_time_days":     c["lead_time_days"],
                "min_order_quantity": c["min_order_quantity"],
                "volume_discounts":   c.get("volume_discounts", []),
                "key_terms":          c.get("key_terms", ""),
                "sla_delivery_pct":   c.get("sla_delivery_compliance_pct"),
            })

        return {
            "status":           "success",
            "category":         cat_norm,
            "contracts":        contracts_out,
            "total_contracts":  len(contracts_out),
            "relevant_clauses": rag_snippets[:3],
        }

    except FileNotFoundError as e:
        return {"status": "error", "message": f"Archivo no encontrado: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error en contract_lookup: {str(e)}"}
