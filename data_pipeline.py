"""Data pipeline for the Data-Driven Stock Analysis dashboard.

Pipeline stages
---------------
1. Acquire the month-wise YAML source data (or synthesise it deterministically
   when the real dataset is unavailable - see DATASET_MISSING.txt).
2. Extract every date-wise entry out of the YAML files and transform it into
   one CSV per symbol (50 files, matching the Nifty 50 universe).
3. Clean and validate the combined frame.
4. Persist the cleaned data to MySQL through ``mysql-connector-python``
   (cursor-based, no SQLAlchemy) with a portable SQLite fallback.

Run standalone::

    python data_pipeline.py
"""

from __future__ import annotations

import math
import random
import sqlite3
import sys
from datetime import date, timedelta

import pandas as pd
import yaml

import config

try:  # pragma: no cover - import guard only
    import mysql.connector
    from mysql.connector import Error as MySQLError

    MYSQL_AVAILABLE = True
except ImportError:  # pragma: no cover
    MYSQL_AVAILABLE = False

    class MySQLError(Exception):
        """Placeholder so except-clauses stay valid without the driver."""


MONTH_NAMES = [
    "01_January", "02_February", "03_March", "04_April",
    "05_May", "06_June", "07_July", "08_August",
    "09_September", "10_October", "11_November", "12_December",
]


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
class Database:
    """Cursor-based SQL wrapper over MySQL, falling back to SQLite."""

    def __init__(self) -> None:
        self.backend = "sqlite"
        self.conn = None
        self._connect()

    def _connect(self) -> None:
        backend = config.DB_BACKEND
        if backend in ("auto", "mysql") and MYSQL_AVAILABLE:
            try:
                self.conn = self._connect_mysql()
                self.backend = "mysql"
                print(f"[db] connected to MySQL {config.MYSQL_CONFIG['host']}:"
                      f"{config.MYSQL_CONFIG['port']}/"
                      f"{config.MYSQL_CONFIG['database']}")
                return
            except MySQLError as exc:
                if backend == "mysql":
                    raise
                print(f"[db] MySQL unavailable ({exc}); falling back to SQLite.")

        self.conn = sqlite3.connect(config.SQLITE_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.backend = "sqlite"
        print(f"[db] connected to SQLite at {config.SQLITE_PATH}")

    @staticmethod
    def _connect_mysql():
        cfg = dict(config.MYSQL_CONFIG)
        database = cfg.pop("database")
        bootstrap = mysql.connector.connect(connection_timeout=5, **cfg)
        cur = bootstrap.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        cur.close()
        bootstrap.close()
        return mysql.connector.connect(connection_timeout=5, database=database, **cfg)

    def _adapt(self, sql: str) -> str:
        if self.backend == "sqlite":
            sql = sql.replace("%s", "?")
        return sql

    def execute(self, sql: str, params: tuple = ()) -> None:
        cur = self.conn.cursor()
        cur.execute(self._adapt(sql), params)
        self.conn.commit()
        cur.close()

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        cur = self.conn.cursor()
        cur.executemany(self._adapt(sql), rows)
        self.conn.commit()
        cur.close()

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        if self.backend == "mysql":
            cur = self.conn.cursor(dictionary=True)
            cur.execute(self._adapt(sql), params)
            rows = cur.fetchall()
        else:
            cur = self.conn.cursor()
            cur.execute(self._adapt(sql), params)
            rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def fetch_df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        return pd.DataFrame(self.fetch_all(sql, params))

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def create_schema(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_prices (
                symbol      VARCHAR(20)  NOT NULL,
                trade_date  DATE         NOT NULL,
                open_price  DOUBLE       NOT NULL,
                high_price  DOUBLE       NOT NULL,
                low_price   DOUBLE       NOT NULL,
                close_price DOUBLE       NOT NULL,
                volume      BIGINT       NOT NULL,
                sector      VARCHAR(40),
                PRIMARY KEY (symbol, trade_date)
            )
            """
        )
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_metrics (
                symbol            VARCHAR(20) PRIMARY KEY,
                sector            VARCHAR(40),
                yearly_return_pct DOUBLE,
                volatility        DOUBLE,
                avg_close         DOUBLE,
                avg_volume        DOUBLE,
                cumulative_return DOUBLE
            )
            """
        )
        print("[db] schema ready (stock_prices, stock_metrics)")

    def load_prices(self, frame: pd.DataFrame) -> None:
        self.execute("DELETE FROM stock_prices")
        rows = [
            (r.symbol, str(r.trade_date), float(r.open_price), float(r.high_price),
             float(r.low_price), float(r.close_price), int(r.volume), r.sector)
            for r in frame.itertuples(index=False)
        ]
        self.executemany(
            "INSERT INTO stock_prices (symbol, trade_date, open_price, high_price, "
            "low_price, close_price, volume, sector) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        print(f"[db] loaded {len(rows)} price rows")

    def load_metrics(self, frame: pd.DataFrame) -> None:
        self.execute("DELETE FROM stock_metrics")
        rows = [
            (r.symbol, r.sector, float(r.yearly_return_pct), float(r.volatility),
             float(r.avg_close), float(r.avg_volume), float(r.cumulative_return))
            for r in frame.itertuples(index=False)
        ]
        self.executemany(
            "INSERT INTO stock_metrics (symbol, sector, yearly_return_pct, "
            "volatility, avg_close, avg_volume, cumulative_return) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )
        print(f"[db] loaded {len(rows)} metric rows")


# ---------------------------------------------------------------------------
# Sector mapping
# ---------------------------------------------------------------------------
def load_sector_map() -> dict[str, str]:
    """Build ticker -> sector from the supplied sector sheet.

    The sheet's ``Symbol`` column holds ``"COMPANY NAME: TICKER"``, so the
    ticker is parsed off the right-hand side. Four tickers that the sheet does
    not carry verbatim are resolved through ``TICKER_SECTOR_OVERRIDES`` (each
    one documented in config.py).
    """
    if not config.SECTOR_CSV.exists():
        print(f"[sector] {config.SECTOR_CSV.name} not found; "
              "falling back to the built-in mapping")
        return dict(config.NIFTY_50)

    sheet = pd.read_csv(config.SECTOR_CSV)
    mapping: dict[str, str] = {}
    for _, row in sheet.iterrows():
        sector = str(row[config.SECTOR_COLUMN_SECTOR]).strip()
        symbol = str(row[config.SECTOR_COLUMN_SYMBOL])
        ticker = symbol.split(":")[-1].strip().upper()
        if ticker:
            mapping[ticker] = sector

    mapping.update(config.TICKER_SECTOR_OVERRIDES)
    print(f"[sector] loaded {len(mapping)} ticker->sector entries from "
          f"{config.SECTOR_CSV.name} "
          f"(+{len(config.TICKER_SECTOR_OVERRIDES)} documented overrides)")
    return mapping


# ---------------------------------------------------------------------------
# Stage 1: source data (YAML, month-wise folders)
# ---------------------------------------------------------------------------
def _trading_days(year: int, count: int) -> list[date]:
    days, cursor = [], date(year, 1, 1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def generate_yaml_source() -> None:
    """Write month-wise YAML folders holding date-wise Nifty 50 entries."""
    rng = random.Random(config.RANDOM_SEED)
    symbols = list(config.NIFTY_50)
    days = _trading_days(config.ANALYSIS_YEAR, config.TRADING_DAYS)

    # Per-symbol regime: starting price, annual drift and daily volatility.
    regime = {}
    for symbol in symbols:
        regime[symbol] = {
            "price": rng.uniform(180.0, 4200.0),
            "drift": rng.gauss(0.00045, 0.00075),
            "vol": rng.uniform(0.009, 0.032),
            "base_volume": rng.randint(400_000, 14_000_000),
        }

    by_month: dict[str, dict[str, list[dict]]] = {name: {} for name in MONTH_NAMES}

    for day_index, trade_day in enumerate(days):
        # A shared market factor makes stocks genuinely correlated.
        market_shock = rng.gauss(0.0, 0.0075)
        month_key = MONTH_NAMES[trade_day.month - 1]
        entries = []
        for symbol in symbols:
            state = regime[symbol]
            beta = 0.4 + (hash(symbol) % 120) / 100.0
            shock = state["drift"] + beta * market_shock + rng.gauss(0.0, state["vol"])
            open_price = state["price"]
            close_price = max(1.0, open_price * math.exp(shock))
            high_price = max(open_price, close_price) * (1 + abs(rng.gauss(0, 0.004)))
            low_price = min(open_price, close_price) * (1 - abs(rng.gauss(0, 0.004)))
            volume = int(state["base_volume"] * rng.uniform(0.45, 1.85))
            state["price"] = close_price

            entries.append(
                {
                    "Ticker": symbol,
                    "date": trade_day.isoformat(),
                    "open": round(open_price, 2),
                    "high": round(high_price, 2),
                    "low": round(low_price, 2),
                    "close": round(close_price, 2),
                    "volume": volume,
                    "month": trade_day.strftime("%Y-%m"),
                }
            )
        by_month[month_key][trade_day.isoformat()] = entries

    for month_key, dated in by_month.items():
        folder = config.YAML_DIR / month_key
        folder.mkdir(parents=True, exist_ok=True)
        for iso_day, entries in dated.items():
            with open(folder / f"{iso_day}.yaml", "w", encoding="utf-8") as handle:
                yaml.safe_dump(entries, handle, sort_keys=False)

    print(f"[yaml] wrote {len(days)} date files across "
          f"{len([m for m in by_month.values() if m])} month folders")


def ensure_yaml_source() -> None:
    existing = list(config.YAML_DIR.glob("*/*.y*ml"))
    if existing:
        print(f"[yaml] found {len(existing)} existing YAML files - reusing")
        return
    print("[yaml] no source YAML found (see DATASET_MISSING.txt); "
          "generating a deterministic dataset with the documented schema")
    generate_yaml_source()


# ---------------------------------------------------------------------------
# Stage 2: YAML -> per-symbol CSV
# ---------------------------------------------------------------------------
_COLUMN_ALIASES = {
    "ticker": "symbol", "symbol": "symbol", "name": "symbol",
    "date": "trade_date", "trade_date": "trade_date",
    "open": "open_price", "high": "high_price",
    "low": "low_price", "close": "close_price",
    "volume": "volume",
}


def read_yaml_records() -> pd.DataFrame:
    """Flatten every month/date YAML file into a single tidy frame."""
    records: list[dict] = []
    files = sorted(config.YAML_DIR.glob("*/*.y*ml"))
    for path in files:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        if isinstance(payload, dict):
            payload = [payload]
        for entry in payload or []:
            row = {
                _COLUMN_ALIASES.get(str(k).lower(), str(k).lower()): v
                for k, v in entry.items()
            }
            records.append(row)

    frame = pd.DataFrame(records)
    print(f"[extract] parsed {len(files)} YAML files -> {len(frame)} rows")
    return frame


def write_symbol_csvs(frame: pd.DataFrame) -> int:
    """Write one CSV per symbol, as required by the specification."""
    for path in config.SYMBOL_CSV_DIR.glob("*.csv"):
        path.unlink()
    count = 0
    for symbol, group in frame.groupby("symbol", sort=True):
        safe = str(symbol).replace("&", "AND").replace("-", "_")
        group.sort_values("trade_date").to_csv(
            config.SYMBOL_CSV_DIR / f"{safe}.csv", index=False
        )
        count += 1
    print(f"[transform] wrote {count} per-symbol CSV files to "
          f"{config.SYMBOL_CSV_DIR.name}/")
    return count


# ---------------------------------------------------------------------------
# Stage 3: cleaning
# ---------------------------------------------------------------------------
def clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce types, drop duplicates and impute gaps."""
    frame = frame.copy()
    before = len(frame)

    numeric = ["open_price", "high_price", "low_price", "close_price", "volume"]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame = frame.dropna(subset=["symbol", "trade_date", "close_price"])
    frame = frame.drop_duplicates(subset=["symbol", "trade_date"], keep="last")
    frame = frame.sort_values(["symbol", "trade_date"])

    # Forward-fill intraday gaps within each symbol, then back-fill any head.
    for column in numeric:
        frame[column] = frame.groupby("symbol")[column].ffill()
        frame[column] = frame.groupby("symbol")[column].bfill()

    frame["volume"] = frame["volume"].fillna(0).astype("int64")

    sector_map = load_sector_map()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    frame["sector"] = frame["symbol"].map(sector_map)
    unmapped = sorted(frame.loc[frame["sector"].isna(), "symbol"].unique())
    if unmapped:
        print(f"[sector] WARNING: {len(unmapped)} unmapped tickers -> {unmapped}")
    frame["sector"] = frame["sector"].fillna("Unclassified")
    frame["trade_date"] = frame["trade_date"].dt.date

    keep = ["symbol", "trade_date", "open_price", "high_price",
            "low_price", "close_price", "volume", "sector"]
    frame = frame[keep].reset_index(drop=True)

    print(f"[clean] {before} -> {len(frame)} rows, "
          f"{frame['symbol'].nunique()} symbols, "
          f"{frame['sector'].nunique()} sectors")
    return frame


def write_sector_mapping(frame: pd.DataFrame) -> None:
    """Persist the resolved ticker -> sector mapping actually used."""
    mapping = (
        frame[["symbol", "sector"]]
        .drop_duplicates()
        .sort_values("symbol")
        .reset_index(drop=True)
    )
    mapping.to_csv(config.SECTOR_MAPPING_CSV, index=False)
    print(f"[transform] resolved sector mapping ({len(mapping)} tickers) "
          f"written to {config.SECTOR_MAPPING_CSV.name}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_pipeline() -> pd.DataFrame:
    ensure_yaml_source()
    raw = read_yaml_records()
    write_symbol_csvs(raw)
    cleaned = clean_frame(raw)
    cleaned.to_csv(config.COMBINED_CSV, index=False)
    write_sector_mapping(cleaned)
    print(f"[data] combined cleaned dataset -> {config.COMBINED_CSV.name}")

    db = Database()
    try:
        db.create_schema()
        db.load_prices(cleaned)
        total = db.fetch_all("SELECT COUNT(*) AS n FROM stock_prices")[0]["n"]
        print(f"[verify] stock_prices row count = {total}")
    finally:
        db.close()
    return cleaned


def load_cleaned() -> pd.DataFrame:
    """Return the cleaned frame, running the pipeline first if required."""
    if config.COMBINED_CSV.exists():
        frame = pd.read_csv(config.COMBINED_CSV, parse_dates=["trade_date"])
        return frame
    frame = run_pipeline()
    return pd.read_csv(config.COMBINED_CSV, parse_dates=["trade_date"])


def main() -> int:
    print("=" * 70)
    print("Data-Driven Stock Analysis - data pipeline")
    print("=" * 70)
    run_pipeline()
    print("\nPipeline completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
