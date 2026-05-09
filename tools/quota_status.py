"""
Tool 3: quota_status
Consulta el cumplimiento de cuota de un comprador con un proveedor en una categoría.
Compara el market share real YTD contra el objetivo del contrato marco y
genera una recomendación de acción.
"""
import json
from datetime import date
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools._shared import DATA_SYNTHETIC


def _load_data():
    import pandas as pd
    txn_path = DATA_SYNTHETIC / "transactions.csv"
    df = pd.read_csv(txn_path, parse_dates=["order_date"])
    contracts_path = DATA_SYNTHETIC / "contracts.json"
    with open(contracts_path, encoding="utf-8") as f:
        contracts = json.load(f)
    return df, contracts


def _get_quota_target(contracts: list, supplier: str, category: str) -> float | None:
    """Busca el market_share_target del proveedor en los contratos vigentes de la categoría."""
    today = date.today().isoformat()
    for c in contracts:
        if category not in c.get("categories", []):
            continue
        if not (c["validity_start"] <= today <= c["validity_end"]):
            continue
        for s in c.get("suppliers", []):
            if s["name"].lower() == supplier.lower():
                return s["market_share_target"]
    return None


class QuotaStatusInput(BaseModel):
    buyer_id: str  = Field(..., description="ID del comprador (ej: buyer_mad_001)")
    supplier: str  = Field(..., description="Nombre del proveedor (ej: Corning, Huawei)")
    category: str  = Field(..., description="Categoría de compra (ej: fibra_optica)")


@tool(args_schema=QuotaStatusInput)
def quota_status(buyer_id: str, supplier: str, category: str) -> dict:
    """
    Calcula el cumplimiento de cuota YTD (Year-to-Date) de un comprador con
    un proveedor en una categoría concreta. Compara el market share real
    versus el objetivo del contrato marco y recomienda si redirigir o
    concentrar compras. Úsala cuando necesites saber si el comprador está
    cumpliendo el acuerdo de cuota o si hay riesgo de incumplimiento.
    """
    try:
        df, contracts = _load_data()

        # Filtrar por comprador y categoría en el año en curso
        current_year = date.today().year
        mask = (
            (df["buyer_id"] == buyer_id) &
            (df["category"] == category) &
            (df["order_date"].dt.year == current_year)
        )
        df_year = df[mask].copy()

        if df_year.empty:
            # Intentar con cualquier año disponible
            mask_any = (df["buyer_id"] == buyer_id) & (df["category"] == category)
            df_year = df[mask_any].copy()
            if df_year.empty:
                return {
                    "status":  "error",
                    "message": f"Sin transacciones para buyer '{buyer_id}' en categoría '{category}'.",
                }
            # Usar el año con más datos
            current_year = df_year["order_date"].dt.year.mode()[0]
            df_year = df_year[df_year["order_date"].dt.year == current_year]

        # Gasto total de la categoría para este comprador en el período
        total_category_spend = df_year["total_eur"].sum()

        # Gasto con el proveedor solicitado
        df_supplier = df_year[df_year["supplier"].str.lower() == supplier.lower()]
        supplier_spend = df_supplier["total_eur"].sum()
        supplier_volume = df_supplier["quantity"].sum()

        current_share = (supplier_spend / total_category_spend) if total_category_spend > 0 else 0.0

        # Obtener objetivo de cuota del contrato
        target_share = _get_quota_target(contracts, supplier, category)

        # Detalle por proveedor en la categoría
        share_by_supplier = (
            df_year.groupby("supplier")["total_eur"]
            .sum()
            .sort_values(ascending=False)
            .apply(lambda x: round(x / total_category_spend * 100, 1) if total_category_spend > 0 else 0)
            .to_dict()
        )

        # Determinar estado y recomendación
        if target_share is None:
            status_vs_target = "sin_contrato"
            recommendation   = (
                f"No hay contrato marco vigente para '{supplier}' en '{category}'. "
                "Considera homologar el proveedor o redirigir a proveedor con contrato."
            )
            gap_pct = None
        else:
            gap = current_share - target_share
            gap_pct = round(gap * 100, 1)

            if abs(gap) <= 0.05:
                status_vs_target = "on_track"
                recommendation   = (
                    f"Cuota de {supplier} en línea con objetivo "
                    f"({current_share:.0%} vs {target_share:.0%}). Mantener ritmo actual."
                )
            elif gap > 0.05:
                status_vs_target = "over"
                recommendation   = (
                    f"Exceso de cuota en {supplier} ({current_share:.0%} vs objetivo {target_share:.0%}, "
                    f"+{gap_pct}pp). Redirigir próximas compras de '{category}' a otros proveedores homologados."
                )
            else:
                missing_eur = abs(gap) * total_category_spend
                status_vs_target = "under"
                recommendation   = (
                    f"Cuota insuficiente en {supplier} ({current_share:.0%} vs objetivo {target_share:.0%}, "
                    f"{gap_pct}pp). Concentrar ~{missing_eur:,.0f} EUR adicionales en este proveedor para cumplir contrato."
                )

        return {
            "status":               "success",
            "buyer_id":             buyer_id,
            "supplier":             supplier,
            "category":             category,
            "year":                 int(current_year),
            "ytd_spent_eur":        round(supplier_spend, 2),
            "ytd_volume_units":     int(supplier_volume),
            "total_category_spend": round(total_category_spend, 2),
            "current_market_share": round(current_share, 4),
            "current_share_pct":    f"{current_share:.1%}",
            "target_market_share":  target_share,
            "target_share_pct":     f"{target_share:.0%}" if target_share else "N/A",
            "gap_pp":               gap_pct,
            "status_vs_target":     status_vs_target,
            "share_by_supplier":    share_by_supplier,
            "recommendation":       recommendation,
        }

    except FileNotFoundError as e:
        return {"status": "error", "message": f"Archivo no encontrado: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error en quota_status: {str(e)}"}
