"""
Tool 4: price_benchmark
Estima el precio justo de un artículo usando histórico de transacciones + XGBoost.
El modelo es SKU-centric: primero busca historial del SKU específico, luego
usa benchmarks de categoría+proveedor como fallback.
Aplica descuentos por volumen del contrato marco si aplica.
"""
import json
import math
from typing import Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools._shared import DATA_SYNTHETIC

_MODEL_CACHE: dict = {}


def _train_or_load_model() -> dict:
    """Entrena XGBoost sobre transactions.csv agrupado por SKU y lo cachea."""
    if _MODEL_CACHE:
        return _MODEL_CACHE

    import pandas as pd
    import numpy as np
    from sklearn.preprocessing import LabelEncoder
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_absolute_percentage_error
    import xgboost as xgb

    df = pd.read_csv(DATA_SYNTHETIC / "transactions.csv", parse_dates=["order_date"])
    df = df[df["unit_price_eur"] > 0].copy()

    df["log_price"]    = np.log1p(df["unit_price_eur"])
    df["log_qty"]      = np.log1p(df["quantity"])
    df["month_sin"]    = np.sin(2 * math.pi * df["order_date"].dt.month / 12)
    df["month_cos"]    = np.cos(2 * math.pi * df["order_date"].dt.month / 12)
    df["has_contract"] = df["has_contract"].astype(int)
    df["is_maverick"]  = df["is_maverick"].astype(int)

    le_sku = LabelEncoder().fit(df["sku"])
    le_cat = LabelEncoder().fit(df["category"])
    le_sup = LabelEncoder().fit(df["supplier"])

    df["sku_enc"] = le_sku.transform(df["sku"])
    df["cat_enc"] = le_cat.transform(df["category"])
    df["sup_enc"] = le_sup.transform(df["supplier"])

    features = ["sku_enc", "cat_enc", "sup_enc", "log_qty",
                "month_sin", "month_cos", "has_contract", "is_maverick"]

    X = df[features].values
    y = df["log_price"].values

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = xgb.XGBRegressor(
        n_estimators=400,
        max_depth=6,
        learning_rate=0.04,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=3,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    mape = mean_absolute_percentage_error(y_test, model.predict(X_test))

    # Estadísticas históricas por SKU (fuente principal de market range)
    sku_stats = (
        df.groupby("sku")["unit_price_eur"]
        .agg(["median", "min", "max", "mean", "count"])
        .reset_index()
        .rename(columns={"count": "n_transactions"})
    )

    # Stats por categoría+proveedor como fallback
    cat_sup_stats = (
        df.groupby(["category", "supplier"])["unit_price_eur"]
        .agg(["median", "min", "max", "mean", "count"])
        .reset_index()
    )

    _MODEL_CACHE.update({
        "model":         model,
        "le_sku":        le_sku,
        "le_cat":        le_cat,
        "le_sup":        le_sup,
        "sku_stats":     sku_stats,
        "cat_sup_stats": cat_sup_stats,
        "mape":          mape,
        "df":            df,
    })
    return _MODEL_CACHE


def _get_volume_discount(contracts: list, category: str, quantity: int) -> float:
    from datetime import date
    today = date.today().isoformat()
    for c in contracts:
        if category not in c.get("categories", []):
            continue
        if not (c["validity_start"] <= today <= c["validity_end"]):
            continue
        for tier in c.get("volume_discounts", []):
            keys = list(tier.keys())
            qty_key_min = [k for k in keys if "min" in k][0]
            qty_key_max = [k for k in keys if "max" in k][0]
            if tier[qty_key_min] <= quantity < tier[qty_key_max]:
                return tier["discount_pct"] / 100.0
    return 0.0


class PriceBenchmarkInput(BaseModel):
    sku: str                  = Field(..., description="SKU del artículo")
    quantity: int             = Field(..., ge=1, description="Cantidad solicitada")
    supplier: Optional[str]   = Field(None, description="Proveedor si ya es conocido")
    target_delivery_days: int = Field(30, ge=1, description="Plazo de entrega deseado en días")


@tool(args_schema=PriceBenchmarkInput)
def price_benchmark(
    sku: str,
    quantity: int,
    supplier: Optional[str] = None,
    target_delivery_days: int = 30,
) -> dict:
    """
    Estima el precio justo de un artículo basándose en el histórico de compras
    y un modelo XGBoost entrenado sobre transacciones reales. Devuelve el rango
    de mercado, el precio estimado, el descuento por volumen aplicable y la
    confianza del modelo. Úsala para validar si el precio ofertado por un
    proveedor es razonable o hay margen de negociación.
    """
    try:
        import pandas as pd
        import numpy as np

        cache = _train_or_load_model()
        model         = cache["model"]
        le_sku        = cache["le_sku"]
        le_cat        = cache["le_cat"]
        le_sup        = cache["le_sup"]
        sku_stats     = cache["sku_stats"]
        cat_sup_stats = cache["cat_sup_stats"]
        df            = cache["df"]
        mape          = cache["mape"]

        # Datos del artículo en catálogo
        catalog = pd.read_csv(DATA_SYNTHETIC / "catalog.csv")
        item_row = catalog[catalog["sku"] == sku]
        if item_row.empty:
            return {"status": "error", "message": f"SKU '{sku}' no encontrado en el catálogo."}

        item          = item_row.iloc[0]
        category      = item["category"]
        catalog_price = float(item["unit_price_eur"])
        eff_supplier  = supplier or item["supplier"]

        # ── Estadísticas históricas para este SKU concreto ─────────────────
        sku_row = sku_stats[sku_stats["sku"] == sku]
        if not sku_row.empty:
            s          = sku_row.iloc[0]
            market_min    = float(s["min"])
            market_max    = float(s["max"])
            market_median = float(s["median"])
            historical_avg = float(s["mean"])
            n_hist        = int(s["n_transactions"])
        else:
            # Fallback: stats de categoría + proveedor
            cs = cat_sup_stats[
                (cat_sup_stats["category"] == category) &
                (cat_sup_stats["supplier"].str.lower() == eff_supplier.lower())
            ]
            if not cs.empty:
                market_min    = float(cs["min"].min())
                market_max    = float(cs["max"].max())
                market_median = float(cs["median"].median())
                historical_avg = float(cs["mean"].mean())
            else:
                market_min    = catalog_price * 0.85
                market_max    = catalog_price * 1.20
                market_median = catalog_price
                historical_avg = catalog_price
            n_hist = 0

        # ── Predicción XGBoost ──────────────────────────────────────────────
        from datetime import date
        today     = date.today()
        month_sin = math.sin(2 * math.pi * today.month / 12)
        month_cos = math.cos(2 * math.pi * today.month / 12)
        log_qty   = math.log1p(quantity)

        with open(DATA_SYNTHETIC / "contracts.json", encoding="utf-8") as f:
            contracts = json.load(f)

        has_contract = any(
            category in c.get("categories", []) and
            c["validity_start"] <= today.isoformat() <= c["validity_end"]
            for c in contracts
        )

        # Encodings con fallback a 0 si el valor no estuvo en entrenamiento
        sku_enc = le_sku.transform([sku])[0] if sku in le_sku.classes_ else 0
        cat_enc = le_cat.transform([category])[0] if category in le_cat.classes_ else 0
        sup_enc = le_sup.transform([eff_supplier])[0] if eff_supplier in le_sup.classes_ else 0

        X_pred        = np.array([[sku_enc, cat_enc, sup_enc, log_qty,
                                   month_sin, month_cos, int(has_contract), 0]])
        log_price_pred = float(model.predict(X_pred)[0])
        ml_price       = math.expm1(log_price_pred)

        # Blending: si hay mucho historial del SKU, confiamos más en el promedio histórico
        if n_hist >= 30:
            estimated_price = 0.6 * historical_avg + 0.4 * ml_price
            confidence      = round(max(0.0, 1.0 - mape * 0.5), 3)
        elif n_hist >= 10:
            estimated_price = 0.4 * historical_avg + 0.6 * ml_price
            confidence      = round(max(0.0, 1.0 - mape * 0.7), 3)
        else:
            estimated_price = ml_price
            confidence      = round(max(0.0, 1.0 - mape), 3)

        # Anclar a rango de mercado para no salir de lo razonable
        estimated_price = max(market_min * 0.9, min(market_max * 1.1, estimated_price))

        # Descuento por volumen
        discount_pct = _get_volume_discount(contracts, category, quantity)
        fair_price   = round(estimated_price * (1 - discount_pct), 4)

        # Alerta de precio
        price_alert = None
        if catalog_price > market_median * 1.20:
            price_alert = (
                f"El precio de catálogo ({catalog_price:.4f} EUR) supera la mediana de mercado "
                f"({market_median:.4f} EUR) en más de un 20%. Revisar antes de aprobar."
            )

        factors = ["historical_transactions", "sku_benchmarks"]
        if discount_pct > 0:
            factors.append(f"volume_discount_{discount_pct*100:.0f}pct")
        if has_contract:
            factors.append("contract_negotiated_price")
        if target_delivery_days < 10:
            factors.append("urgency_premium")

        return {
            "status":                      "success",
            "sku":                         sku,
            "item_name":                   str(item["name"]),
            "category":                    category,
            "supplier":                    eff_supplier,
            "quantity":                    quantity,
            "uom":                         str(item["uom"]),
            "catalog_price_eur":           round(catalog_price, 4),
            "historical_avg_price_eur":    round(historical_avg, 4),
            "historical_n_transactions":   n_hist,
            "current_market_range": {
                "min":    round(market_min, 4),
                "max":    round(market_max, 4),
                "median": round(market_median, 4),
            },
            "estimated_fair_price_eur":    round(fair_price, 4),
            "total_estimated_eur":         round(fair_price * quantity, 2),
            "volume_discount_applicable":  discount_pct > 0,
            "discount_percentage":         round(discount_pct * 100, 1),
            "has_active_contract":         has_contract,
            "confidence":                  confidence,
            "factors_considered":          factors,
            "price_alert":                 price_alert,
        }

    except FileNotFoundError as e:
        return {"status": "error", "message": f"Archivo no encontrado: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"Error en price_benchmark: {str(e)}"}
