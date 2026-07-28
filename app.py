"""Streamlit dashboard for Data-Driven Stock Analysis.

Pages
-----
Market Overview · Top Performers · Volatility Analysis · Cumulative Returns ·
Sector Performance · Correlation Heatmap · Monthly Gainers & Losers ·
Risk/Return Segments (ML) · Stock Explorer

Run::

    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import config
import models
from data_pipeline import load_cleaned

st.set_page_config(
    page_title="Nifty 50 Stock Performance Dashboard",
    page_icon="📈",
    layout="wide",
)

PAGES = [
    "Market Overview",
    "Top Performers",
    "Volatility Analysis",
    "Cumulative Returns",
    "Sector Performance",
    "Correlation Heatmap",
    "Monthly Gainers & Losers",
    "Risk/Return Segments (ML)",
    "Stock Explorer",
]


# ---------------------------------------------------------------------------
# Cached data access
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading cleaned price data…")
def get_prices() -> pd.DataFrame:
    frame = load_cleaned()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


@st.cache_data(show_spinner="Computing per-symbol metrics…")
def get_metrics(prices: pd.DataFrame) -> pd.DataFrame:
    return models.compute_stock_metrics(prices)


def artefacts_ready() -> bool:
    return models.SCALER_PKL.exists() and models.KMEANS_PKL.exists()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_market_overview(prices: pd.DataFrame, metrics: pd.DataFrame) -> None:
    st.header("📊 Market Overview")
    summary = models.market_summary(metrics)

    row = st.columns(5)
    row[0].metric("Stocks tracked", summary["total_stocks"])
    row[1].metric("Green stocks", summary["green_stocks"],
                  f"{summary['green_pct']}%")
    row[2].metric("Red stocks", summary["red_stocks"], f"{summary['red_pct']}%")
    row[3].metric("Average close", f"₹{summary['average_price']:,.2f}")
    row[4].metric("Average volume", f"{summary['average_volume']:,.0f}")

    left, right = st.columns(2)
    mix = pd.DataFrame(
        {
            "outcome": ["Green", "Red"],
            "count": [summary["green_stocks"], summary["red_stocks"]],
        }
    )
    left.plotly_chart(
        px.pie(mix, names="outcome", values="count", hole=0.45,
               color="outcome",
               color_discrete_map={"Green": "#2ca02c", "Red": "#d62728"},
               title="Green vs red stocks"),
        use_container_width=True,
    )
    right.plotly_chart(
        px.histogram(metrics, x="yearly_return_pct", nbins=25,
                     title="Distribution of yearly returns (%)"),
        use_container_width=True,
    )

    index_series = (
        prices.groupby("trade_date")["close_price"].mean().reset_index()
    )
    st.plotly_chart(
        px.line(index_series, x="trade_date", y="close_price",
                title="Equal-weighted Nifty 50 index level"),
        use_container_width=True,
    )


def page_top_performers(metrics: pd.DataFrame) -> None:
    st.header("🏆 Top Performers")
    green = models.top_green_stocks(metrics)
    loss = models.top_loss_stocks(metrics)

    left, right = st.columns(2)
    left.subheader("Top 10 green stocks")
    left.plotly_chart(
        px.bar(green, x="symbol", y="yearly_return_pct", color="sector",
               title="Best yearly returns (%)"),
        use_container_width=True,
    )
    left.dataframe(green[["symbol", "sector", "yearly_return_pct", "last_close"]],
                   use_container_width=True, hide_index=True)

    right.subheader("Top 10 loss stocks")
    right.plotly_chart(
        px.bar(loss, x="symbol", y="yearly_return_pct", color="sector",
               title="Worst yearly returns (%)"),
        use_container_width=True,
    )
    right.dataframe(loss[["symbol", "sector", "yearly_return_pct", "last_close"]],
                    use_container_width=True, hide_index=True)


def page_volatility(metrics: pd.DataFrame) -> None:
    st.header("📉 Volatility Analysis")
    st.caption(
        "Volatility = standard deviation of daily returns, annualised by √252. "
        "Higher volatility implies higher risk."
    )
    top = models.most_volatile(metrics, config.TOP_N)
    st.plotly_chart(
        px.bar(top, x="symbol", y="volatility", color="sector",
               title=f"Top {config.TOP_N} most volatile stocks"),
        use_container_width=True,
    )
    st.plotly_chart(
        px.scatter(metrics, x="volatility", y="yearly_return_pct", color="sector",
                   hover_name="symbol", size="avg_volume",
                   title="Risk versus return"),
        use_container_width=True,
    )
    st.dataframe(top, use_container_width=True, hide_index=True)


def page_cumulative(prices: pd.DataFrame, metrics: pd.DataFrame) -> None:
    st.header("📈 Cumulative Returns")
    default = metrics.nlargest(config.TOP_N_CUMULATIVE,
                               "cumulative_return")["symbol"].tolist()
    chosen = st.multiselect(
        "Symbols", sorted(metrics["symbol"]), default=default
    )
    if not chosen:
        st.info("Select at least one symbol.")
        return
    series = models.cumulative_return_series(prices, chosen)
    series["cumulative_return_pct"] = series["cumulative_return"] * 100
    st.plotly_chart(
        px.line(series, x="trade_date", y="cumulative_return_pct", color="symbol",
                title="Cumulative return over the year (%)"),
        use_container_width=True,
    )


def page_sector(metrics: pd.DataFrame) -> None:
    st.header("🏭 Sector Performance")
    sectors = models.sector_performance(metrics)
    st.plotly_chart(
        px.bar(sectors, x="sector", y="avg_yearly_return_pct",
               color="avg_yearly_return_pct",
               color_continuous_scale="RdYlGn",
               title="Average yearly return by sector (%)"),
        use_container_width=True,
    )
    st.dataframe(sectors, use_container_width=True, hide_index=True)


def page_correlation(prices: pd.DataFrame) -> None:
    st.header("🔗 Stock Price Correlation")
    st.caption("Correlation of daily close-price percentage change.")
    limit = st.slider("Number of symbols to display", 10, 50, 30, step=5)
    matrix = models.correlation_matrix(prices)
    subset = matrix.iloc[:limit, :limit]
    st.plotly_chart(
        px.imshow(subset, color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                  aspect="auto", title="Correlation heatmap"),
        use_container_width=True,
    )


def page_monthly(prices: pd.DataFrame) -> None:
    st.header("🗓️ Monthly Top 5 Gainers & Losers")
    monthly = models.monthly_gainers_losers(prices)
    months = sorted(monthly["month"].unique())
    chosen = st.select_slider("Month", options=months, value=months[0])

    view = monthly[
        (monthly["month"] == chosen) & (monthly["bucket"] != "Mid")
    ].sort_values("monthly_return_pct", ascending=False)

    st.plotly_chart(
        px.bar(view, x="symbol", y="monthly_return_pct", color="bucket",
               color_discrete_map={"Gainer": "#2ca02c", "Loser": "#d62728"},
               title=f"Top 5 gainers and losers — {chosen}"),
        use_container_width=True,
    )
    st.dataframe(
        view[["symbol", "sector", "monthly_return_pct", "bucket"]],
        use_container_width=True, hide_index=True,
    )

    with st.expander("Show all 12 months at once"):
        grid = monthly[monthly["bucket"] != "Mid"]
        st.plotly_chart(
            px.bar(grid, x="symbol", y="monthly_return_pct", color="bucket",
                   facet_col="month", facet_col_wrap=3, height=1400,
                   color_discrete_map={"Gainer": "#2ca02c", "Loser": "#d62728"},
                   title="Top 5 gainers and losers for every month"),
            use_container_width=True,
        )


def page_segments(metrics: pd.DataFrame) -> None:
    st.header("🤖 Risk/Return Segments (KMeans)")
    if not artefacts_ready():
        st.warning("Model artefacts missing. Run `python models.py` first.")
        return
    labelled = models.assign_clusters(metrics)
    st.plotly_chart(
        px.scatter(labelled, x="volatility", y="yearly_return_pct",
                   color="segment", hover_name="symbol", size="avg_volume",
                   title="KMeans segmentation of the Nifty 50 universe"),
        use_container_width=True,
    )
    st.dataframe(
        labelled[["symbol", "sector", "segment", "yearly_return_pct",
                  "volatility", "avg_close"]].sort_values("segment"),
        use_container_width=True, hide_index=True,
    )


def page_explorer(prices: pd.DataFrame, metrics: pd.DataFrame) -> None:
    st.header("🔍 Stock Explorer")
    symbol = st.selectbox("Symbol", sorted(prices["symbol"].unique()))
    detail = prices[prices["symbol"] == symbol].sort_values("trade_date")
    row = metrics[metrics["symbol"] == symbol].iloc[0]

    cols = st.columns(4)
    cols[0].metric("Yearly return", f"{row['yearly_return_pct']:.2f}%")
    cols[1].metric("Volatility", f"{row['volatility']:.4f}")
    cols[2].metric("Average close", f"₹{row['avg_close']:,.2f}")
    cols[3].metric("Average volume", f"{row['avg_volume']:,.0f}")

    st.plotly_chart(
        px.line(detail, x="trade_date", y="close_price",
                title=f"{symbol} — close price"),
        use_container_width=True,
    )
    st.plotly_chart(
        px.bar(detail, x="trade_date", y="volume", title=f"{symbol} — volume"),
        use_container_width=True,
    )
    st.dataframe(detail.tail(30), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def main() -> None:
    st.sidebar.title("📈 Nifty 50 Dashboard")
    choice = st.sidebar.radio("Navigate", PAGES)
    st.sidebar.divider()
    st.sidebar.caption(
        "Backend: MySQL via mysql-connector-python "
        "(automatic SQLite fallback). No SQLAlchemy."
    )

    prices = get_prices()
    metrics = get_metrics(prices)

    if choice == "Market Overview":
        page_market_overview(prices, metrics)
    elif choice == "Top Performers":
        page_top_performers(metrics)
    elif choice == "Volatility Analysis":
        page_volatility(metrics)
    elif choice == "Cumulative Returns":
        page_cumulative(prices, metrics)
    elif choice == "Sector Performance":
        page_sector(metrics)
    elif choice == "Correlation Heatmap":
        page_correlation(prices)
    elif choice == "Monthly Gainers & Losers":
        page_monthly(prices)
    elif choice == "Risk/Return Segments (ML)":
        page_segments(metrics)
    elif choice == "Stock Explorer":
        page_explorer(prices, metrics)


if __name__ == "__main__":
    main()
