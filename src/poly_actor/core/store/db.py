"""DuckDB connection over the Parquet files in data/."""

import duckdb

from poly_actor.config import DB_PATH, ensure_dirs


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if not read_only:
        ensure_dirs()
    return duckdb.connect(str(DB_PATH), read_only=read_only)
