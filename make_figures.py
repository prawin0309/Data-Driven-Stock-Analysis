"""Render static figures for the README and the project report.

Covers every visualization the brief asks for: top gainers/losers, volatility,
cumulative return, sector performance, correlation heatmap and month-wise
gainers/losers. Run after the pipeline and models:

    python data_pipeline.py
    python models.py
    python make_figures.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
import models  # noqa: E402
from data_pipeline import load_cleaned  # noqa: E402

FIG_DIR = Path(__file__).resolve().parent / "reports" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

GREEN, RED, BLUE = "#2E7D32", "#C62828", "#2E5E8A"
plt.rcParams.update({
    "figure.dpi": 120,
    "savefig.bbox": "tight",
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 9,
})


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(FIG_DIR / name)
    plt.close(fig)
    print(f"[fig] {name}")


def main() -> None:
    prices = models.add_daily_returns(load_cleaned())
    metrics = pd.read_csv(config.METRICS_CSV)

    # 1. Top 10 green / top 10 loss
    top = metrics.nlargest(10, "yearly_return_pct")
    bottom = metrics.nsmallest(10, "yearly_return_pct")
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    axes[0].barh(top["symbol"][::-1], top["yearly_return_pct"][::-1],
                 color=GREEN)
    axes[0].set_title("Top 10 green stocks")
    axes[0].set_xlabel("Return over window (%)")
    axes[1].barh(bottom["symbol"][::-1], bottom["yearly_return_pct"][::-1],
                 color=RED)
    axes[1].set_title("Top 10 loss stocks")
    axes[1].set_xlabel("Return over window (%)")
    save(fig, "01_top_green_and_loss.png")

    # 2. Volatility
    vol = metrics.nlargest(10, "volatility")
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.bar(vol["symbol"], vol["volatility"], color=BLUE)
    ax.set_title("Top 10 most volatile stocks")
    ax.set_ylabel("Std. dev. of daily returns")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    save(fig, "02_volatility_top10.png")

    # 3. Cumulative return, top 5
    top5 = metrics.nlargest(5, "yearly_return_pct")["symbol"].tolist()
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for symbol in top5:
        sub = prices[prices["symbol"] == symbol].sort_values("trade_date")
        cumulative = (1 + sub["daily_return"].fillna(0)).cumprod() - 1
        ax.plot(pd.to_datetime(sub["trade_date"]), cumulative * 100,
                label=symbol, linewidth=1.4)
    ax.set_title("Cumulative return - top 5 performers")
    ax.set_ylabel("Cumulative return (%)")
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    save(fig, "03_cumulative_return_top5.png")

    # 4. Sector performance
    sector = models.sector_performance(metrics).sort_values(
        "avg_yearly_return_pct"
    )
    colours = [GREEN if v >= 0 else RED
               for v in sector["avg_yearly_return_pct"]]
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.barh(sector["sector"], sector["avg_yearly_return_pct"], color=colours)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Average return by sector")
    ax.set_xlabel("Average return over window (%)")
    save(fig, "04_sector_performance.png")

    # 5. Correlation heatmap (top 20 by traded value, else unreadable)
    liquid = metrics.nlargest(20, "avg_volume")["symbol"].tolist()
    corr = models.correlation_matrix(prices).loc[liquid, liquid]
    fig, ax = plt.subplots(figsize=(7, 6))
    image = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(liquid)), liquid, rotation=90, fontsize=7)
    ax.set_yticks(range(len(liquid)), liquid, fontsize=7)
    ax.set_title("Daily-return correlation (20 most traded)")
    ax.grid(False)
    fig.colorbar(image, ax=ax, shrink=0.8)
    save(fig, "05_correlation_heatmap.png")

    # 6. Month-wise top 5 gainers and losers
    frame = prices.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame["month"] = frame["trade_date"].dt.to_period("M").astype(str)
    monthly = (frame.sort_values("trade_date")
               .groupby(["symbol", "month"], as_index=False)
               .agg(first=("close_price", "first"),
                    last=("close_price", "last")))
    monthly["ret"] = (monthly["last"] - monthly["first"]) / monthly["first"] * 100
    months = sorted(monthly["month"].unique())
    cols = 4
    rows = (len(months) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 2.6 * rows))
    for ax, month in zip(axes.ravel(), months):
        sub = monthly[monthly["month"] == month]
        picked = pd.concat([sub.nlargest(5, "ret"), sub.nsmallest(5, "ret")])
        picked = picked.sort_values("ret")
        ax.barh(picked["symbol"], picked["ret"],
                color=[GREEN if v >= 0 else RED for v in picked["ret"]])
        ax.set_title(month, fontsize=9)
        ax.tick_params(labelsize=7)
        ax.axvline(0, color="black", linewidth=0.6)
    for ax in axes.ravel()[len(months):]:
        ax.axis("off")
    fig.suptitle("Top 5 gainers and losers by month", y=1.0)
    fig.tight_layout()
    save(fig, "06_monthly_gainers_losers.png")

    print(f"\n{len(list(FIG_DIR.glob('*.png')))} figures -> {FIG_DIR}")


if __name__ == "__main__":
    main()
