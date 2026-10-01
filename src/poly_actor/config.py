"""Project paths and environment loading. All timestamps in this project are UTC."""

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
DB_PATH = DATA_DIR / "poly_actor.duckdb"
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


def ensure_dirs() -> None:
    for d in (RAW_DIR, CLEAN_DIR):
        d.mkdir(parents=True, exist_ok=True)
