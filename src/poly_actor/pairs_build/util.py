"""Small helpers shared by the pair builders: Gamma field parsing and YAML flow style."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml


class Flow(dict):
    """dict rendered in YAML flow style ({a: 1, b: 2}) to keep long lists compact."""


def _flow_repr(dumper: yaml.SafeDumper, data: Flow) -> Any:
    return dumper.represent_mapping("tag:yaml.org,2002:map", dict(data), flow_style=True)


yaml.SafeDumper.add_representer(Flow, _flow_repr)


def iso(ts: str | None) -> str | None:
    """Normalise any Gamma timestamp to ISO-8601 UTC with a trailing Z."""
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def yes_token(m: dict) -> tuple[str, float | None]:
    """-> (Yes token id, final/current Yes price or None when Gamma omits it)."""
    outs = json.loads(m["outcomes"])
    toks = json.loads(m["clobTokenIds"])
    i = outs.index("Yes")
    raw = m.get("outcomePrices")
    price = float(json.loads(raw)[i]) if raw else None
    return toks[i], price


def vol(x: Any) -> float:
    return round(float(x or 0), 2)


def ceil_hour(iso_z: str) -> str:
    """Round a UTC ISO time UP to the next whole hour (unchanged if already on the hour)."""
    dt = datetime.fromisoformat(iso_z.replace("Z", "+00:00"))
    floor = dt.replace(minute=0, second=0, microsecond=0)
    if dt > floor:
        floor += timedelta(hours=1)
    return floor.isoformat().replace("+00:00", "Z")


def plus_hours(iso_z: str, hours: int) -> str:
    return (
        (datetime.fromisoformat(iso_z.replace("Z", "+00:00")) + timedelta(hours=hours))
        .isoformat()
        .replace("+00:00", "Z")
    )
