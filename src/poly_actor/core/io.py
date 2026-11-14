"""Strict-JSON conversion and atomic file writes shared by every study."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


def jsonable(obj: object) -> Any:
    """Replace NaN/inf by None and numpy scalars/arrays by Python values (strict JSON).

    Raises ``TypeError`` for any other type, so a stray object fails here, by name.
    """
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        return float(obj) if math.isfinite(obj) else None
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if obj is None or isinstance(obj, str | int):  # int covers bool
        return obj
    raise TypeError(f"not JSON-serialisable: {type(obj).__name__}")


def write_json(doc: object, path: Path) -> None:
    """Strict JSON, written atomically (see `write_text_atomic`)."""
    write_text_atomic(json.dumps(jsonable(doc), indent=1, allow_nan=False), path)


def write_text_atomic(text: str, path: Path, newline: str | None = None) -> None:
    """Write to a uniquely named temp file in the same folder, then rename (atomic).

    ``newline`` is passed to `open` (None = platform default, "\\n" = LF everywhere)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
