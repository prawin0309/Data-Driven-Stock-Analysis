"""Analytical and machine-learning engines for the stock dashboard.

Analytics
---------
* Per-symbol yearly return, volatility, cumulative return, average price/volume
* Top-10 green and top-10 loss stocks
* Market summary (green vs red count, average price, average volume)
* Sector-wise average yearly return
* Close-price correlation matrix
* Month-wise top-5 gainers and losers

Machine learning
----------------
* ``KMeans`` risk/return segmentation of the 50 stocks (with ``StandardScaler``)
* ``LinearRegression`` market-beta model per stock, regressing each stock's
  daily return against the equal-weighted market return

Both models plus the scaler are persisted as ``.pkl`` artefacts.

Run standalone::

    python models.py
"""

from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

import config
from data_pipeline import Database, load_cleaned

SCALER_PKL = config.ARTIFACT_DIR / "risk_return_scaler.pkl"
KMEANS_PKL = config.ARTIFACT_DIR / "risk_return_kmeans.pkl"
BETA_PKL = config.ARTIFACT_DIR / "market_beta_models.pkl"

TRADING_DAYS_PER_YEAR = 252


def _save(obj, path) -> None:
    with open(path, "wb") as handle:
        pickle.dump(obj, handle)
    print(f"[save] {path.name}")


def load_artifact(path):
    with open(path, "rb") as handle:
        return pickle.load(handle)


# ---------------------------------------------------------------------------
# Core derived frames
# ---------------------------------------------------------------------------
def add_daily_returns(frame: pd.DataFrame) -> pd.DataFrame:
    """Append the daily return column: (close - prev_close) / prev_close."""
    frame = frame.sort_values(["symbol", "trade_date"]).copy()
    frame["prev_close"] = frame.groupby("symbol")["close_price"].shift(1)
    frame["daily_return"] = (
        frame["close_price"] - frame["prev_close"]
    ) / frame["prev_close"]
    return frame


def close_price_pivot(frame: pd.DataFrame) -> pd.DataFrame:
    """Wide frame: rows = trade_date, columns = symbol, values = close."""
    return frame.pivot_table(
        index="trade_date", columns="symbol", values="close_price"
    ).sort_index()


def compute_stock_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per symbol with the headline performance metrics."""
    enriched = add_daily_returns(frame)
    rows = []
    for symbol, group in enriched.groupby("symbol"):
        group = group.sort_values("trade_date")
        first_close = float(group["close_price"].iloc[0])
        last_close = float(group["close_price"].iloc[-1])
        returns = group["daily_return"].dropna()
        rows.append(
            {
                "symbol": symbol,
                "sector": group["sector"].iloc[0],
                "first_close": round(first_close, 2),
                "last_close": round(last_close, 2),
                "yearly_return_pct": round(
                    100.0 * (last_close - first_close) / first_close, 4
                ),
                "volatility": round(
                    float(returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)), 6
                ),
                "daily_volatility": round(float(returns.std()), 6),
                "avg_close": round(float(group["close_price"].mean()), 2),
                "avg_volume": round(float(group["volume"].mean()), 2),
                "cumulative_return": round(float((1 + returns).prod() - 1), 6),
            }
        )
    metrics = pd.DataFrame(rows).sort_values(
        "yearly_return_pct", ascending=False
    ).reset_index(drop=True)
    return metrics


# ---------------------------------------------------------------------------
# Requirement-driven analytics
# ---------------------------------------------------------------------------
def top_green_stocks(metrics: pd.DataFrame, n: int = config.TOP_N) -> pd.DataFrame:
    return metrics.nlargest(n, "yearly_return_pct").reset_index(drop=True)


def top_loss_stocks(metrics: pd.DataFrame, n: int = config.TOP_N) -> pd.DataFrame:
    return metrics.nsmallest(n, "yearly_return_pct").reset_index(drop=True)


def market_summary(metrics: pd.DataFrame) -> dict:
    green = int((metrics["yearly_return_pct"] > 0).sum())
    red = int((metrics["yearly_return_pct"] <= 0).sum())
    total = len(metrics)
    return {
        "total_stocks": total,
        "green_stocks": green,
        "red_stocks": red,
        "green_pct": round(100.0 * green / total, 2) if total else 0.0,
        "red_pct": round(100.0 * red / total, 2) if total else 0.0,
        "average_price": round(float(metrics["avg_close"].mean()), 2),
        "average_volume": round(float(metrics["avg_volume"].mean()), 2),
        "average_yearly_return_pct": round(
            float(metrics["yearly_return_pct"].mean()), 4
        ),
    }


def most_volatile(metrics: pd.DataFrame, n: int = config.TOP_N) -> pd.DataFrame:
    return metrics.nlargest(n, "volatility")[
        ["symbol", "sector", "volatility", "yearly_return_pct"]
    ].reset_index(drop=True)


def cumulative_return_series(frame: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Long frame of running cumulative return for the requested symbols."""
    enriched = add_daily_returns(frame)
    subset = enriched[enriched["symbol"].isin(symbols)].copy()
    subset["daily_return"] = subset["daily_return"].fillna(0.0)
    subset["cumulative_return"] = (
        subset.groupby("symbol")["daily_return"].transform(
            lambda series: (1 + series).cumprod() - 1
        )
    )
    return subset[["trade_date", "symbol", "cumulative_return"]]


def sector_performance(metrics: pd.DataFrame) -> pd.DataFrame:
    return (
        metrics.groupby("sector", as_index=False)
        .agg(
            avg_yearly_return_pct=("yearly_return_pct", "mean"),
            avg_volatility=("volatility", "mean"),
            stocks=("symbol", "count"),
        )
        .sort_values("avg_yearly_return_pct", ascending=False)
        .round(4)
        .reset_index(drop=True)
    )


def correlation_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Correlation of daily close-price percentage change across stocks."""
    pivot = close_price_pivot(frame)
    return pivot.pct_change().corr()


def monthly_gainers_losers(frame: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """Per-month percentage return for every stock, ranked within the month."""
    working = frame.copy()
    working["trade_date"] = pd.to_datetime(working["trade_date"])
    working["month"] = working["trade_date"].dt.to_period("M").astype(str)
    working = working.sort_values(["symbol", "trade_date"])

    monthly = working.groupby(["month", "symbol"], as_index=False).agg(
        first_close=("close_price", "first"),
        last_close=("close_price", "last"),
        sector=("sector", "first"),
    )
    monthly["monthly_return_pct"] = (
        100.0 * (monthly["last_close"] - monthly["first_close"])
        / monthly["first_close"]
    ).round(4)

    monthly["rank_gain"] = monthly.groupby("month")["monthly_return_pct"].rank(
        ascending=False, method="first"
    )
    monthly["rank_loss"] = monthly.groupby("month")["monthly_return_pct"].rank(
        ascending=True, method="first"
    )
    monthly["bucket"] = np.where(
        monthly["rank_gain"] <= top_n,
        "Gainer",
        np.where(monthly["rank_loss"] <= top_n, "Loser", "Mid"),
    )
    return monthly


# ---------------------------------------------------------------------------
# ML engine 1: KMeans risk / return segmentation
# ---------------------------------------------------------------------------
def train_risk_return_clusters(metrics: pd.DataFrame, n_clusters: int = 4) -> dict:
    features = metrics[
        ["yearly_return_pct", "volatility", "avg_volume", "avg_close"]
    ].to_numpy(dtype=float)

    scaler = StandardScaler().fit(features)
    scaled = scaler.transform(features)

    kmeans = KMeans(n_clusters=n_clusters, random_state=config.RANDOM_SEED, n_init=10)
    labels = kmeans.fit_predict(scaled)
    score = float(silhouette_score(scaled, labels))

    _save(scaler, SCALER_PKL)
    _save(kmeans, KMEANS_PKL)

    print(f"[cluster] k={n_clusters}  silhouette={score:.4f}")
    return {"labels": labels, "silhouette": score, "n_clusters": n_clusters}


def assign_clusters(metrics: pd.DataFrame) -> pd.DataFrame:
    """Attach a human-readable risk/return segment to each stock."""
    scaler = load_artifact(SCALER_PKL)
    kmeans = load_artifact(KMEANS_PKL)
    features = metrics[
        ["yearly_return_pct", "volatility", "avg_volume", "avg_close"]
    ].to_numpy(dtype=float)
    labelled = metrics.copy()
    labelled["cluster"] = kmeans.predict(scaler.transform(features))

    profile = labelled.groupby("cluster").agg(
        ret=("yearly_return_pct", "mean"),
        vol=("volatility", "mean"),
        size=("symbol", "count"),
    )
    # Rank-based naming keeps every segment label distinct even when several
    # clusters sit on the same side of the median.
    return_rank = profile["ret"].rank(ascending=False).astype(int)
    risk_rank = profile["vol"].rank(ascending=False).astype(int)
    return_tier = {1: "Top", 2: "Upper", 3: "Lower", 4: "Bottom"}
    risk_tier = {1: "highest", 2: "high", 3: "moderate", 4: "low"}

    names = {}
    for cluster in profile.index:
        names[cluster] = (
            f"{return_tier.get(return_rank.loc[cluster], 'Mid')}-quartile return"
            f" / {risk_tier.get(risk_rank.loc[cluster], 'mid')} risk"
            f" ({profile.loc[cluster, 'ret']:+.0f}%, "
            f"vol {profile.loc[cluster, 'vol']:.2f})"
        )
    labelled["segment"] = labelled["cluster"].map(names)
    return labelled


# ---------------------------------------------------------------------------
# ML engine 2: market-beta linear regression
# ---------------------------------------------------------------------------
def train_market_beta(frame: pd.DataFrame) -> pd.DataFrame:
    """Regress each stock's daily return on the equal-weighted market return."""
    enriched = add_daily_returns(frame)
    market = (
        enriched.groupby("trade_date")["daily_return"].mean().rename("market_return")
    )

    bundle, rows = {}, []
    for symbol, group in enriched.groupby("symbol"):
        merged = group.set_index("trade_date").join(market).dropna(
            subset=["daily_return", "market_return"]
        )
        if len(merged) < 30:
            continue
        x = merged[["market_return"]].to_numpy(dtype=float)
        y = merged["daily_return"].to_numpy(dtype=float)
        model = LinearRegression().fit(x, y)
        bundle[symbol] = model
        rows.append(
            {
                "symbol": symbol,
                "sector": group["sector"].iloc[0],
                "beta": round(float(model.coef_[0]), 4),
                "alpha_daily": round(float(model.intercept_), 6),
                "r2": round(float(model.score(x, y)), 4),
            }
        )

    _save(bundle, BETA_PKL)
    beta_frame = pd.DataFrame(rows).sort_values("beta", ascending=False)
    print(f"[beta] fitted {len(beta_frame)} regressions, "
          f"mean R2={beta_frame['r2'].mean():.3f}")
    return beta_frame.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_all() -> dict:
    frame = load_cleaned()
    metrics = compute_stock_metrics(frame)
    metrics.to_csv(config.METRICS_CSV, index=False)
    print(f"[data] per-symbol metrics -> {config.METRICS_CSV.name}")

    cluster_info = train_risk_return_clusters(metrics)
    beta_frame = train_market_beta(frame)

    db = Database()
    try:
        db.create_schema()
        db.load_metrics(metrics)
    finally:
        db.close()

    return {
        "frame": frame,
        "metrics": metrics,
        "clusters": cluster_info,
        "beta": beta_frame,
    }


def main() -> int:
    print("=" * 70)
    print("Data-Driven Stock Analysis - metrics and model training")
    print("=" * 70)
    result = build_all()
    metrics = result["metrics"]

    print("\nMarket summary")
    for key, value in market_summary(metrics).items():
        print(f"  {key:<28} {value}")

    print("\nTop 10 green stocks")
    print(top_green_stocks(metrics)[
        ["symbol", "sector", "yearly_return_pct"]].to_string(index=False))

    print("\nTop 10 loss stocks")
    print(top_loss_stocks(metrics)[
        ["symbol", "sector", "yearly_return_pct"]].to_string(index=False))

    print("\nTop 10 most volatile stocks")
    print(most_volatile(metrics).to_string(index=False))

    print("\nSector-wise average yearly return")
    print(sector_performance(metrics).to_string(index=False))

    print("\nRisk / return segments")
    print(assign_clusters(metrics)["segment"].value_counts().to_string())

    print("\nMarket beta (top 5 by beta)")
    print(result["beta"].head().to_string(index=False))

    print("\nModel training completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
