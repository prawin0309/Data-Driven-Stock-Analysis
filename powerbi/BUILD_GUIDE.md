# Power BI Dashboard — Build Guide

Target: **~25 minutes**, 4 pages, 11 visuals. Everything below is drag-and-drop; no Power Query transformation is required because `export_powerbi_data.py` already writes flat tables.

## 0. Regenerate the data (only if the pipeline was re-run)

```bash
cd D:\DS_G\Data_Driven_Stock_Analysis
python powerbi/export_powerbi_data.py
```

## 1. Load

**Home → Get data → Text/CSV**, load all six files from `powerbi\data\`:

| File | Rows | Role |
|---|---|---|
| `fact_prices.csv` | 14,200 | Fact — one row per symbol per trading day |
| `dim_stock_metrics.csv` | 50 | Dimension — one row per symbol, all summary metrics |
| `agg_sector_performance.csv` | 21 | Sector rollup |
| `agg_monthly_returns.csv` | 700 | Monthly return + rank per symbol |
| `agg_correlation_long.csv` | 2,500 | Unpivoted correlation matrix |
| `kpi_market_summary.csv` | 1 | KPI card values |

Confirm `trade_date` imports as **Date** and `month` as **Text**. If `trade_date` comes in as Text, select the column → Column tools → Data type → Date.

## 2. Relationships (Model view)

Create these three, all **many-to-one, single direction**:

- `fact_prices[symbol]` → `dim_stock_metrics[symbol]`
- `agg_monthly_returns[symbol]` → `dim_stock_metrics[symbol]`
- `agg_correlation_long[symbol_a]` → `dim_stock_metrics[symbol]`

Power BI usually auto-detects these. Delete any auto-relationship on `sector` — the sector column exists in several tables and an extra join creates ambiguous filter paths.

## 3. Measures

Create on `dim_stock_metrics` (**Home → New measure**). Only the first three are required; the rest sharpen the cards.

```dax
Green Stocks = CALCULATE(COUNTROWS(dim_stock_metrics), dim_stock_metrics[performance] = "Green")

Red Stocks = CALCULATE(COUNTROWS(dim_stock_metrics), dim_stock_metrics[performance] = "Red")

Avg Yearly Return % = AVERAGE(dim_stock_metrics[yearly_return_pct])

Avg Close Price = AVERAGE(fact_prices[close_price])

Avg Daily Volume = AVERAGE(fact_prices[volume])

Green Share % = DIVIDE([Green Stocks], COUNTROWS(dim_stock_metrics), 0) * 100
```

## 4. Pages

### Page 1 — Market Overview
- **5 Card visuals**: `Green Stocks`, `Red Stocks`, `Avg Yearly Return %`, `Avg Close Price`, `Avg Daily Volume`
- **Donut chart**: Legend `dim_stock_metrics[performance]`, Values `Count of symbol`
- **Slicer**: `dim_stock_metrics[sector]` (set to Dropdown in Format → Slicer settings)

### Page 2 — Top Performers
- **Bar chart (Top 10 Green)**: Y `symbol`, X `yearly_return_pct`, Filter type *Top N* → Top 10 by `yearly_return_pct`
- **Bar chart (Top 10 Loss)**: same, but *Bottom 10*
- **Bar chart (Most Volatile)**: Y `symbol`, X `volatility`, Top N → Top 10 by `volatility`

Colour the green chart `#2E7D32` and the loss chart `#C62828` — it reads instantly in a live demo.

### Page 3 — Sector & Correlation
- **Bar chart**: Y `agg_sector_performance[sector]`, X `avg_yearly_return_pct`, sorted descending
- **Matrix**: Rows `symbol_a`, Columns `symbol_b`, Values `correlation` (Average). Format → Cell elements → **Background color → On** for a heatmap effect. Filter to ~15 symbols first or the matrix becomes unreadable.
- **Line chart**: X `fact_prices[trade_date]`, Y `close_price`, Legend `symbol`, filtered to the top 5 by cumulative return

### Page 4 — Monthly Gainers & Losers
- **Slicer**: `agg_monthly_returns[month]` (Tile style, so all 14 months are visible at once)
- **Bar chart (Top 5 Gainers)**: Y `symbol`, X `monthly_return_pct`, filter `rank_in_month` is ≤ 5
- **Bar chart (Top 5 Losers)**: Y `symbol`, X `monthly_return_pct`, Bottom 5 by `monthly_return_pct`

## 5. Save

Save as `D:\DS_G\Data_Driven_Stock_Analysis\powerbi\stock_dashboard.pbix`, then **File → Export → Export to PDF** and keep the PDF next to it. The PDF is what an evaluator can open without Power BI installed — worth the extra 30 seconds.

## Note on the analysis window

The supplied YAML archive spans **2023-10 through 2024-11** — 14 months, 284 trading days, 50 tickers. "Yearly return" throughout this dashboard means first-to-last close across that full window, not a calendar year. Say this out loud in the demo; it is the most likely question an evaluator asks about the numbers.
