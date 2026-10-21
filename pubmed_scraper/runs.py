"""Finding fetch runs on disk, and how update runs chain onto a full run.

Each topic folder under data/raw/ holds runs of three kinds (manifest "mode"):

    full     every paper matching the query
    sample   the newest N papers, for a quick look        (fetch --limit N)
    update   papers added or changed since the last run    (fetch --update)

A topic's current dataset is its latest full run plus every update made on top
of it. When the same paper appears in more than one of those runs, the newest
copy wins: PubMed records keep changing after they appear (MeSH indexing is
added weeks later, retractions get marked, errors get corrected).
"""

import json
from pathlib import Path


def read_manifest(run_dir):
    return json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))


def mode_of(manifest):
    """Runs made before update mode existed have no "mode" field."""
    return manifest.get("mode") or ("sample" if manifest.get("sample_limit") else "full")


def finished_runs(topic_dir):
    """Runs in a topic folder that finished (have a manifest), oldest first.
    Run folders are named by start time, so name order is time order."""
    topic_dir = Path(topic_dir)
    if not topic_dir.is_dir():
        return []
    return sorted(p for p in topic_dir.iterdir() if (p / "manifest.json").is_file())


def latest_run(data_dir, topic, modes=None):
    """Newest finished run for a topic, optionally only of the given modes."""
    for run in reversed(finished_runs(Path(data_dir) / "raw" / topic)):
        if modes is None or mode_of(read_manifest(run)) in modes:
            return run
    return None


def chain(run_dir):
    """The runs that make up the dataset ending at run_dir, oldest first.
    A full or sample run stands alone; an update brings its full run and every
    update between them."""
    run_dir = Path(run_dir)
    manifest = read_manifest(run_dir)
    if mode_of(manifest) != "update":
        return [run_dir]
    base = run_dir.parent / manifest["base_run"]
    if not (base / "manifest.json").is_file():
        raise SystemExit(f"update run {run_dir.name} is based on {base.name}, "
                         f"which is missing from {run_dir.parent}")
    updates = []
    for r in finished_runs(run_dir.parent):
        if base.name < r.name <= run_dir.name:
            m = read_manifest(r)
            if mode_of(m) == "update" and m.get("base_run") == base.name:
                updates.append(r)
    return [base] + updates
