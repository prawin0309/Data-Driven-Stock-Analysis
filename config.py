"""Configuration for the Data-Driven Stock Analysis dashboard."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
YAML_DIR = DATA_DIR / "yaml_monthly"
SYMBOL_CSV_DIR = DATA_DIR / "symbol_csv"
ARTIFACT_DIR = BASE_DIR / "artifacts"

for _folder in (DATA_DIR, YAML_DIR, SYMBOL_CSV_DIR, ARTIFACT_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

COMBINED_CSV = DATA_DIR / "all_stocks_cleaned.csv"
SECTOR_CSV = DATA_DIR / "sector_data.csv"
SECTOR_MAPPING_CSV = DATA_DIR / "sector_mapping.csv"
METRICS_CSV = DATA_DIR / "stock_metrics.csv"
SQLITE_PATH = DATA_DIR / "guvi_db.sqlite3"

MYSQL_CONFIG = {
    "host": os.getenv("STOCK_DB_HOST", "localhost"),
    "port": int(os.getenv("STOCK_DB_PORT", "3306")),
    "user": os.getenv("STOCK_DB_USER", "root"),
    "password": os.getenv("STOCK_DB_PASSWORD", "root"),
    "database": os.getenv("STOCK_DB_NAME", "guvi_db"),
}
DB_BACKEND = os.getenv("STOCK_DB_BACKEND", "auto").lower()

RANDOM_SEED = 42
TRADING_DAYS = 248
ANALYSIS_YEAR = 2024

# The supplied YAML archive spans 2023-10 through 2024-11 (14 month folders,
# 284 trading days, 50 tickers). "Yearly return" below therefore means
# first-to-last close across the full supplied window.
SECTOR_COLUMN_COMPANY = "COMPANY"
SECTOR_COLUMN_SECTOR = "sector"
SECTOR_COLUMN_SYMBOL = "Symbol"

# Four tickers appear in the YAML archive under names the sector sheet does not
# carry verbatim. Each mapping below is an explicit, documented decision:
#   ADANIENT    - sheet lists "ADANI ENTERPRISES" but mis-types its symbol as
#                 ADANIGREEN; matched by company name instead.
#   BHARTIARTL  - sheet lists "BHARTI AIRTEL" with symbol AIRTEL.
#   TATACONSUM  - sheet lists "TATA CONSUMER" with symbol TATACONSUMER.
#   BRITANNIA   - absent from the sheet entirely; classified by hand alongside
#                 the other packaged-foods constituents.
TICKER_SECTOR_OVERRIDES = {
    "ADANIENT": "MISCELLANEOUS",
    "BHARTIARTL": "TELECOM",
    "TATACONSUM": "FMCG",
    "BRITANNIA": "FOOD & TOBACCO",
}

# Nifty 50 constituents with their sector classification.
NIFTY_50 = {
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy",
    "COALINDIA": "Energy", "NTPC": "Energy", "POWERGRID": "Energy",
    "TCS": "IT", "INFY": "IT", "HCLTECH": "IT", "WIPRO": "IT",
    "TECHM": "IT", "LTIM": "IT",
    "HDFCBANK": "Financials", "ICICIBANK": "Financials",
    "KOTAKBANK": "Financials", "AXISBANK": "Financials",
    "SBIN": "Financials", "INDUSINDBK": "Financials",
    "BAJFINANCE": "Financials", "BAJAJFINSV": "Financials",
    "HDFCLIFE": "Financials", "SBILIFE": "Financials",
    "SHRIRAMFIN": "Financials",
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG", "TATACONSUM": "FMCG",
    "MARUTI": "Automobile", "M&M": "Automobile", "TATAMOTORS": "Automobile",
    "BAJAJ-AUTO": "Automobile", "EICHERMOT": "Automobile",
    "HEROMOTOCO": "Automobile",
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma",
    "DIVISLAB": "Pharma", "APOLLOHOSP": "Healthcare",
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "ADANIENT": "Metals",
    "ULTRACEMCO": "Construction", "GRASIM": "Construction",
    "LT": "Construction", "ADANIPORTS": "Infrastructure",
    "BHARTIARTL": "Telecom", "TITAN": "Consumer Durables",
    "ASIANPAINT": "Consumer Durables",
}

TOP_N = 10
TOP_N_CUMULATIVE = 5
