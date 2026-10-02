"""DuckDB views over the immutable raw Parquet files (read-only; nothing is copied).

- raw_polymarket_prices(token_id, fidelity, t, ts, p): de-duplicated on (token, fidelity, t).
- raw_stock_bars(ticker, ts, open, high, low, close, volume, ohlc_all_nan): ts is the bar
  START (UTC); de-duplicated on (ticker, ts). Re-stamping to bar end happens in step 4.
- raw_manifest_polymarket / raw_manifest_stocks: the JSONL fetch logs.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from poly_actor.config import RAW_DIR

_FN = "replace(filename, chr(92), '/')"  # Windows-safe path
_PM_COLS = "CAST(NULL AS VARCHAR) token_id, CAST(NULL AS INTEGER) fidelity, CAST(NULL AS BIGINT) t, CAST(NULL AS TIMESTAMPTZ) ts, CAST(NULL AS DOUBLE) p"  # noqa: E501
_ST_COLS = 'CAST(NULL AS VARCHAR) ticker, CAST(NULL AS TIMESTAMPTZ) ts, CAST(NULL AS DOUBLE) "open", CAST(NULL AS DOUBLE) high, CAST(NULL AS DOUBLE) low, CAST(NULL AS DOUBLE) "close", CAST(NULL AS DOUBLE) volume, CAST(NULL AS BOOLEAN) ohlc_all_nan'  # noqa: E501


def _has(raw: Path, pattern: str) -> bool:
    return any(raw.glob(pattern))


def create_raw_views(con: duckdb.DuckDBPyConnection, raw_dir: Path = RAW_DIR) -> None:
    raw = Path(raw_dir)
    base = raw.as_posix()
    if _has(raw, "polymarket/*/fid=*/*.parquet"):
        con.execute(rf"""
            CREATE OR REPLACE VIEW raw_polymarket_prices AS
            SELECT regexp_extract({_FN}, 'polymarket/([^/]+)/fid=', 1) AS token_id,
                   CAST(regexp_extract({_FN}, 'fid=([0-9]+)/', 1) AS INTEGER) AS fidelity,
                   t, ts, p
            FROM read_parquet('{base}/polymarket/*/fid=*/*.parquet', filename=true)
            QUALIFY row_number() OVER (PARTITION BY token_id, fidelity, t ORDER BY filename) = 1
        """)
    else:
        con.execute(
            f"CREATE OR REPLACE VIEW raw_polymarket_prices AS SELECT {_PM_COLS} WHERE false"
        )
    if _has(raw, "stocks/*/*.parquet"):
        con.execute(f"""
            CREATE OR REPLACE VIEW raw_stock_bars AS
            SELECT regexp_extract({_FN}, 'stocks/([^/]+)/', 1) AS ticker,
                   ts, "open", high, low, "close", volume, ohlc_all_nan
            FROM read_parquet('{base}/stocks/*/*.parquet', filename=true)
            QUALIFY row_number() OVER (PARTITION BY ticker, ts ORDER BY filename) = 1
        """)
    else:
        con.execute(f"CREATE OR REPLACE VIEW raw_stock_bars AS SELECT {_ST_COLS} WHERE false")
    for src, name in (("polymarket", "raw_manifest_polymarket"), ("stocks", "raw_manifest_stocks")):
        m = raw / src / "_manifest.jsonl"
        if m.exists() and m.stat().st_size:
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS "
                f"SELECT * FROM read_json_auto('{m.as_posix()}', "
                "format='newline_delimited', ignore_errors=true)"
            )
