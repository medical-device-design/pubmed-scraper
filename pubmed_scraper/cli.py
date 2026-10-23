"""Command line. Run with the virtual environment active (see README):

    python -m pubmed_scraper topics                       list topics and queries
    python -m pubmed_scraper count in_vitro               papers matching a topic
    python -m pubmed_scraper fetch in_vitro --limit 200   sample: 200 most recent
    python -m pubmed_scraper fetch in_vitro               everything matching
    python -m pubmed_scraper fetch in_vitro --update      only what changed since the last run
    python -m pubmed_scraper fetch in_vitro --auto        full if none exists yet, else update
    python -m pubmed_scraper annotate in_vitro            PubTator3 entities for fetched papers
    python -m pubmed_scraper parse in_vitro               saved data -> tables
    python -m pubmed_scraper runs in_vitro                list fetch runs on disk

To run everything unattended (e.g. on the VM), see scripts/run_pipeline.sh.
"""

import argparse
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG, get_topic, load_topics
from .eutils import EUtils
from .export import export
from .fetch import fetch
from .parse import iter_runs
from .pubtator import annotate, iter_annotations
from .runs import chain, latest_run, mode_of, read_manifest
from .settings import DATA_DIR


def target_run(data_dir, topic, run=None):
    """The run a command works on: --run if given, else the newest finished run."""
    if run:
        path = Path(run)
        if not path.is_dir():
            path = Path(data_dir) / "raw" / topic / run       # a bare run name
        if not (path / "manifest.json").is_file():
            raise SystemExit(f"{path} is not a finished fetch run (no manifest.json)")
        return path
    found = latest_run(data_dir, topic)
    if found is None:
        raise SystemExit(f"no finished fetch for {topic!r} under {Path(data_dir) / 'raw' / topic}. "
                         f"Run `fetch` first.")
    return found


def list_runs(topic_dir):
    """Every run folder for a topic, finished or not, with what it holds."""
    folders = sorted(p for p in topic_dir.iterdir() if p.is_dir()) if topic_dir.is_dir() else []
    if not folders:
        print(f"no runs under {topic_dir}")
        return
    print(f"{'run':<17} {'mode':<7} {'papers':>8}  {'PubTator3':<12} note")
    for r in folders:
        if not (r / "manifest.json").is_file():
            print(f"{r.name:<17} {'-':<7} {'-':>8}  {'-':<12} unfinished (in progress, or stopped)")
            continue
        m = read_manifest(r)
        if (r / "pubtator" / "manifest.json").is_file():
            pt = "done"
        elif (r / "pubtator").is_dir():
            pt = "partial"
        else:
            pt = "not yet"
        note = f"on top of {m['base_run']}" if mode_of(m) == "update" else ""
        print(f"{r.name:<17} {mode_of(m):<7} {m['records_returned']:>8,}  {pt:<12} {note}")


def describe(runs):
    parts = [f"{r.name} ({mode_of(read_manifest(r))})" for r in runs]
    return parts[0] if len(parts) == 1 else f"{parts[0]} + {len(parts) - 1} update(s), latest {runs[-1].name}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pubmed_scraper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(DEFAULT_CONFIG),
                    help="topics file (default: topics.toml in the repo)")
    ap.add_argument("--data-dir", default=str(DATA_DIR),
                    help="where raw and processed data go (default: data/ in the repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("topics", help="list configured topics and their full queries")
    p.add_argument("--names", action="store_true", help="only the names, one per line (for scripts)")

    p = sub.add_parser("count", help="how many PubMed papers match a topic")
    p.add_argument("topic")

    p = sub.add_parser("fetch", help="download raw PubMed XML for a topic")
    p.add_argument("topic")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--limit", type=int, help="sample size (most recent first); omit for all")
    g.add_argument("--update", action="store_true",
                   help="only papers added or changed since the last full/update run")
    g.add_argument("--auto", action="store_true",
                   help="update if a full run exists for the current query, else a full fetch")
    p.add_argument("--batch-size", type=int, default=200, help="records per EFetch request")

    p = sub.add_parser("annotate", help="download PubTator3 entity annotations for fetched papers")
    p.add_argument("topic")
    p.add_argument("--run", help="run name or folder (default: latest finished, with its updates)")
    p.add_argument("--force", action="store_true", help="re-download even if already annotated")

    p = sub.add_parser("parse", help="turn saved data into JSONL and CSV tables")
    p.add_argument("topic")
    p.add_argument("--run", help="run name or folder (default: latest finished, with its updates)")

    p = sub.add_parser("runs", help="list the fetch runs saved for a topic")
    p.add_argument("topic")

    a = ap.parse_args(argv)

    if a.cmd == "topics":
        for name, t in load_topics(a.config).items():
            print(name if a.names else f"{name}  ({t.label})\n  {t.full_query}\n")
        return 0

    topic = get_topic(a.topic, a.config)

    if a.cmd == "count":
        n = EUtils().esearch_count(topic.full_query)
        print(f"{topic.label}: {n:,} papers\n  query: {topic.full_query}")
        return 0

    if a.cmd == "fetch":
        fetch(topic, data_dir=a.data_dir, limit=a.limit, update=a.update, auto=a.auto,
              batch_size=a.batch_size)
        return 0

    if a.cmd == "runs":
        list_runs(Path(a.data_dir) / "raw" / topic.name)
        return 0

    runs = chain(target_run(a.data_dir, topic.name, a.run))

    if a.cmd == "annotate":
        print(f"PubTator3 annotations for {describe(runs)}")
        for r in runs:
            annotate(r, force=a.force)
        return 0

    if a.cmd == "parse":
        sources = [{"run": r.name, **read_manifest(r)} for r in runs]
        annotated = [r for r in runs if (r / "pubtator" / "manifest.json").is_file()]
        stats, ann_stats = {}, {}
        annotations = iter_annotations(runs, ann_stats) if annotated else None
        out = Path(a.data_dir) / "processed" / topic.name / runs[-1].name
        s = export(iter_runs(runs, stats), out, topic.name, sources, stats, annotations, ann_stats)

        print(f"parsed {s['records']:,} papers from {describe(runs)}")
        print(f"  with abstract {s['with_abstract']:,} | DOI {s['with_doi']:,} | in PMC {s['in_pmc']:,} | "
              f"grants {s['with_grant']:,} | retracted {s['retracted']:,}")
        print(f"  NCT id (PubMed link) {s['with_nct_id']:,} | NCT id in text {s['with_nct_id_in_text']:,} | "
              f"FDA number in text {s['with_fda_number']:,}")
        if annotations is None:
            print(f"  no PubTator3 annotations yet; run: python -m pubmed_scraper annotate {topic.name}")
        else:
            pt = s["pubtator"]
            print(f"  PubTator3: {pt['papers_annotated']:,} papers, {pt['entity_rows']:,} entities "
                  f"({pt['normalized_entity_rows']:,} with an ID), {pt['relation_rows']:,} relations")
            if pt["runs_not_annotated"]:
                print(f"  note: not annotated yet: {', '.join(pt['runs_not_annotated'])} "
                      f"(run `annotate {topic.name}`)")
        print(f"  wrote {out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
