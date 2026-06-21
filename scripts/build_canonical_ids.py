"""
Pipeline de canonicalización del catálogo — SmartProc Copilot.

Resuelve el problema de los duplicados como una propiedad DEL CATÁLOGO (offline),
no de cada búsqueda. Asigna a cada artículo un `canonical_id` (= producto real) y
un `canonical_name`, y los persiste en data/synthetic/catalog.csv.

Dos tiers:
  Tier 1 (exacto)    — agrupa por nombre normalizado. Cubre ~90% del catálogo de
                       forma determinista, sin modelo (la serie EXT-* es un catálogo
                       espejo con nombre idéntico al SKU canónico).
  Tier 2 (semántico) — los duplicados parafraseados (SKUs *-DUP-*) no comparten
                       nombre exacto. Se enganchan a su canónico por similitud de
                       embedding, bloqueando por category + uom para no cruzar
                       familias distintas.

Idempotente: se puede re-ejecutar; recalcula las dos columnas desde cero.

Uso:
    python scripts/build_canonical_ids.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

# Permitir importar tools/ al ejecutar como script
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools._shared import DATA_SYNTHETIC, embed  # noqa: E402

CATALOG = DATA_SYNTHETIC / "catalog.csv"

# Umbral mínimo de similitud para enganchar un DUP a un canónico existente.
# Por debajo, el artículo se considera producto propio (no duplicado).
TIER2_THRESHOLD = 0.55


def _norm(s: str) -> str:
    """Normaliza un nombre para comparación exacta: minúsculas, espacios colapsados."""
    return re.sub(r"\s+", " ", str(s).strip().lower())


def build_canonical_ids(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Devuelve (df con columnas canonical_id/canonical_name, reporte)."""
    df = df.copy()
    is_dup = df["is_duplicate"].astype(str).str.lower().isin(["true", "1"])

    # ── Tier 1: agrupación exacta por nombre normalizado ──────────────────────
    # Los DUP parafraseados quedan fuera (se resuelven en Tier 2).
    df["_norm_name"] = df["name"].map(_norm)
    canonical_id = {}      # norm_name -> CAN-####
    canonical_name = {}    # CAN-#### -> nombre representativo
    next_id = 1
    for _, row in df[~is_dup].iterrows():
        nn = row["_norm_name"]
        if nn not in canonical_id:
            cid = f"CAN-{next_id:04d}"
            canonical_id[nn] = cid
            canonical_name[cid] = row["name"]
            next_id += 1

    df["canonical_id"] = df["_norm_name"].map(canonical_id)

    # ── Tier 2: matching semántico de los DUP parafraseados ───────────────────
    # Representante por canónico: primer artículo no-EXT si existe (nombre "oficial").
    reps = (
        df[~is_dup]
        .sort_values(by="sku", key=lambda s: s.str.startswith("EXT-"))  # no-EXT primero
        .groupby("canonical_id", sort=False)
        .first()
        .reset_index()
    )
    rep_texts = (reps["name"] + ". " + reps["description"]).tolist()
    rep_vecs = embed(rep_texts)

    tier2_matches = []
    dup_rows = df[is_dup]
    if len(dup_rows):
        dup_texts = (dup_rows["name"] + ". " + dup_rows["description"]).tolist()
        dup_vecs = embed(dup_texts)

        for (idx, row), qv in zip(dup_rows.iterrows(), dup_vecs):
            # Bloqueo: solo canónicos de la misma category + uom
            mask = (reps["category"] == row["category"]) & (reps["uom"] == row["uom"])
            if not mask.any():
                tier2_matches.append((row["sku"], None, 0.0, "sin candidatos en bloque"))
                continue
            cand_idx = mask[mask].index.to_numpy()
            sims = rep_vecs[cand_idx] @ qv
            best_local = int(sims.argmax())
            best_score = float(sims[best_local])
            best_cid = reps.iloc[cand_idx[best_local]]["canonical_id"]
            best_name = canonical_name[best_cid]

            if best_score >= TIER2_THRESHOLD:
                df.at[idx, "canonical_id"] = best_cid
                tier2_matches.append((row["sku"], best_name, best_score, "enganchado"))
            else:
                # Producto propio: le creamos su propio canónico
                cid = f"CAN-{next_id:04d}"
                next_id += 1
                df.at[idx, "canonical_id"] = cid
                canonical_name[cid] = row["name"]
                tier2_matches.append((row["sku"], None, best_score, "producto único"))

    # ── canonical_name para todas las filas ───────────────────────────────────
    df["canonical_name"] = df["canonical_id"].map(canonical_name)
    df = df.drop(columns=["_norm_name"])

    n_canon = df["canonical_id"].nunique()
    n_items = len(df)
    n_redundant = n_items - n_canon
    matched = sum(1 for _, _, _, st in tier2_matches if st == "enganchado")

    report = {
        "total_items": n_items,
        "canonical_products": n_canon,
        "redundant_variants": n_redundant,
        "tier2_total": len(tier2_matches),
        "tier2_matched": matched,
        "tier2_matches": tier2_matches,
    }
    return df, report


def main() -> None:
    df = pd.read_csv(CATALOG)
    df, rep = build_canonical_ids(df)
    df.to_csv(CATALOG, index=False)

    print("─" * 64)
    print("CANONICALIZACIÓN DEL CATÁLOGO")
    print("─" * 64)
    print(f"  Artículos en catálogo : {rep['total_items']}")
    print(f"  Productos reales       : {rep['canonical_products']}")
    print(f"  Variantes redundantes  : {rep['redundant_variants']} "
          f"({100 * rep['redundant_variants'] // rep['total_items']}% del catálogo era ruido)")
    print(f"  DUP parafraseados      : {rep['tier2_matched']}/{rep['tier2_total']} "
          f"enganchados por matching semántico (umbral {TIER2_THRESHOLD})")
    print("─" * 64)
    print("  Detalle Tier 2 (matching semántico):")
    for sku, name, score, status in rep["tier2_matches"]:
        tgt = f"→ {name}" if name else "(producto único)"
        print(f"    {sku:<14} {score:.3f}  {status:<14} {tgt}")
    print("─" * 64)
    print(f"  Columnas canonical_id / canonical_name escritas en {CATALOG}")


if __name__ == "__main__":
    main()
