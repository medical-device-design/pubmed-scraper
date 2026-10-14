"""Loads topics.toml and builds each topic's full PubMed query."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("topics.toml")


@dataclass(frozen=True)
class Topic:
    name: str
    label: str
    query: str          # the topic part only
    full_query: str     # (device_filter) AND (topic part)


def load_topics(path=DEFAULT_CONFIG):
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"config not found: {path} (run from the repo root, or pass --config)")
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    device = (cfg.get("device_filter") or {}).get("query", "").strip()
    topics = {}
    for name, t in (cfg.get("topics") or {}).items():
        q = t["query"].strip()
        full = f"({device}) AND ({q})" if device else q
        topics[name] = Topic(name=name, label=t.get("label", name), query=q, full_query=full)
    return topics


def get_topic(name, path=DEFAULT_CONFIG):
    topics = load_topics(path)
    if name not in topics:
        known = ", ".join(sorted(topics)) or "(none)"
        raise SystemExit(f"unknown topic {name!r}. Topics in {path}: {known}")
    return topics[name]
