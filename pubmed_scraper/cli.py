"""Command line: topics, count, fetch, parse. Run with the virtual environment
active (see README):

    python -m pubmed_scraper topics
    python -m pubmed_scraper count in_vitro
    python -m pubmed_scraper fetch in_vitro --limit 200   # sample: most recent 200
    python -m pubmed_scraper fetch in_vitro               # everything matching
    python -m pubmed_scraper parse in_vitro               # latest finished fetch
"""

import argparse
import json
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, get_topic, load_topics
from .eutils import EUtils
from .export import export
from .fetch import fetch
from .parse import iter_run
from .settings import DATA_DIR


def latest_run(data_dir, topic):
    """Newest raw run for a topic that finished (has a manifest)."""
    base = Path(data_dir) / "raw" / topic
    runs = sorted(p for p in base.glob("*") if (p / "manifest.json").exists()) if base.exists() else []
    if not runs:
        raise SystemExit(f"no finished fetch for {topic!r} under {base}. Run `fetch` first.")
    return runs[-1]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pubmed_scraper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="topics file (default: topics.toml in the repo)")
    ap.add_argument("--data-dir", default=str(DATA_DIR),
                    help="where raw and processed data go (default: data/ in the repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("topics", help="list configured topics and their full queries")

    p = sub.add_parser("count", help="how many PubMed papers match a topic")
    p.add_argument("topic")

    p = sub.add_parser("fetch", help="download raw PubMed XML for a topic")
    p.add_argument("topic")
    p.add_argument("--limit", type=int, help="sample size (most recent first); omit for all")
    p.add_argument("--batch-size", type=int, default=200, help="records per EFetch request")

    p = sub.add_parser("parse", help="turn a saved fetch into JSONL and CSV tables")
    p.add_argument("topic")
    p.add_argument("--run", help="raw run folder to parse (default: latest finished)")

    a = ap.parse_args(argv)

    if a.cmd == "topics":
        for name, t in load_topics(a.config).items():
            print(f"{name}  ({t.label})\n  {t.full_query}\n")
        return 0

    topic = get_topic(a.topic, a.config)

    if a.cmd == "count":
        n = EUtils().esearch_count(topic.full_query)
        print(f"{topic.label}: {n:,} papers\n  query: {topic.full_query}")
        return 0

    if a.cmd == "fetch":
        fetch(topic, data_dir=a.data_dir, limit=a.limit, batch_size=a.batch_size)
        return 0

    if a.cmd == "parse":
        run = Path(a.run) if a.run else latest_run(a.data_dir, topic.name)
        manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        stats = {}
        out = Path(a.data_dir) / "processed" / topic.name / run.name
        summary = export(iter_run(run, stats), out, topic.name, manifest, stats)
        print(f"parsed {summary['records']:,} papers from {run}")
        print(f"  with abstract {summary['with_abstract']:,} | DOI {summary['with_doi']:,} | "
              f"in PMC {summary['in_pmc']:,} | NCT id {summary['with_nct_id']:,} | "
              f"FDA number {summary['with_fda_number']:,} | retracted {summary['retracted']:,}")
        print(f"  wrote {out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
