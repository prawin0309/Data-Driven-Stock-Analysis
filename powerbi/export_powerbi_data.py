"""Export flat, Power BI-ready tables for the Stock Performance dashboard.

Power BI reads CSV natively, so this writes denormalised tables that need no
transformation inside Power Query. Run from the project root:

    python powerbi/export_powerbi_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import models  # noqa: E402
from data_pipeline import load_cleaned  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    prices = load_cleaned()
    prices = models.add_daily_returns(prices)

    # 1. Fact table: one row per symbol per trading day.
    fact = prices[[
        "symbol", "sector", "trade_date", "open_price", "high_price",
        "low_price", "close_price", "volume", "daily_return",
    ]].copy()
    fact["trade_date"] = pd.to_datetime(fact["trade_date"])
    fact["month"] = fact["trade_date"].dt.to_period("M").astype(str)
    fact["year"] = fact["trade_date"].dt.year
    fact.to_csv(OUT_DIR / "fact_prices.csv", index=False)

    # 2. Dimension: one row per symbol with the summary metrics.
    metrics = models.compute_stock_metrics(prices)
    metrics["performance"] = metrics["yearly_return_pct"].apply(
        lambda v: "Green" if v >= 0 else "Red"
    )
    metrics.to_csv(OUT_DIR / "dim_stock_metrics.csv", index=False)

    # 3. Sector rollup.
    models.sector_performance(metrics).to_csv(
        OUT_DIR / "agg_sector_performance.csv", index=False
    )

    # 4. Monthly return per symbol (drives the month-wise gainers/losers page).
    monthly = (
        fact.sort_values("trade_date")
        .groupby(["symbol", "month"], as_index=False)
        .agg(first_close=("close_price", "first"),
             last_close=("close_price", "last"),
             avg_volume=("volume", "mean"))
    )
    monthly["monthly_return_pct"] = (
        (monthly["last_close"] - monthly["first_close"])
        / monthly["first_close"] * 100
    ).round(4)
    monthly = monthly.merge(
        metrics[["symbol", "sector"]], on="symbol", how="left"
    )
    monthly["rank_in_month"] = monthly.groupby("month")["monthly_return_pct"] \
        .rank(ascending=False, method="first").astype(int)
    monthly.to_csv(OUT_DIR / "agg_monthly_returns.csv", index=False)

    # 5. Correlation matrix, unpivoted so Power BI can render a matrix visual.
    corr = models.correlation_matrix(prices)
    corr.index.name = "symbol_a"
    corr.columns.name = "symbol_b"
    long = corr.stack().rename("correlation").reset_index()
    long.to_csv(OUT_DIR / "agg_correlation_long.csv", index=False)

    # 6. Single-row market summary for the KPI cards.
    summary = models.market_summary(metrics)
    pd.DataFrame([summary]).to_csv(OUT_DIR / "kpi_market_summary.csv",
                                   index=False)

    for path in sorted(OUT_DIR.glob("*.csv")):
        rows = sum(1 for _ in path.open(encoding="utf-8")) - 1
        print(f"[powerbi] {path.name:32s} {rows:>8,} rows")
    print(f"\nLoad these six CSVs into Power BI Desktop from {OUT_DIR}")


if __name__ == "__main__":
    main()
