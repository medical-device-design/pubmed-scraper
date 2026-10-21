"""Search PubMed for a topic and save the raw records, untouched, to disk.

Each run writes a new folder:

    data/raw/<topic>/<YYYYMMDD-HHMMSS>/
        pmids.txt            every PMID requested, one per line
        efetch-00001.xml     raw PubMed XML, one file per batch
        manifest.json        query, counts, checksums; written LAST

Parsing works only from these saved files, so the data can be re-processed
without contacting NCBI again. A run with no manifest.json did not finish and
is ignored by `parse`.

Three modes (see runs.py): full, sample (--limit), and update (--update).

An update fetches papers whose PubMed record CHANGED since the previous run,
not just papers that are new. That matters for our query: it filters on MeSH
indexing, which NLM adds weeks after a paper first appears, so a paper often
only starts matching once it is indexed. Searching by modification date
catches it then. It also catches corrections and newly marked retractions.

Updates cannot see papers that stop matching or are deleted from PubMed, so
run a full fetch now and then (for example every quarter) to reset.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import __version__
from .eutils import EUtils
from .runs import latest_run, mode_of, read_manifest

ESEARCH_CAP = 9999                  # ESearch cannot return more than 10,000 PubMed IDs per query
FULL_START = date(1800, 1, 1)
UPDATE_OVERLAP = timedelta(days=1)  # re-check the day before the last run; duplicates are dropped


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fmt(d):
    return d.strftime("%Y/%m/%d")


def date_windows(client, term, start, end, datetype="pdat"):
    """Yield (mindate, maxdate) windows covering start..end (inclusive dates)
    that each hold at most ESEARCH_CAP records, by halving the range until
    every piece fits. Raises if a single day holds more than the cap, rather
    than silently returning a truncated list."""
    n = client.esearch_count(term, _fmt(start), _fmt(end), datetype)
    if n == 0:
        return
    if n <= ESEARCH_CAP:
        yield _fmt(start), _fmt(end)
        return
    if start == end:
        raise RuntimeError(f"{n:,} records on {start} alone, over the ESearch cap; narrow the query")
    mid = start + (end - start) // 2
    yield from date_windows(client, term, start, mid, datetype)
    yield from date_windows(client, term, mid + timedelta(days=1), end, datetype)


def collect_pmids(client, term, start, end, datetype="pdat", log=print):
    """Every PMID matching term with a `datetype` date in start..end."""
    pmids = set()
    for lo, hi in date_windows(client, term, start, end, datetype):
        ids = client.esearch_ids(term, retmax=ESEARCH_CAP, mindate=lo, maxdate=hi, datetype=datetype)
        pmids.update(ids)
        log(f"  {lo} to {hi}: {len(ids):,} PMIDs (total so far {len(pmids):,})")
    return sorted(pmids, key=int)


def plan_update(data_dir, topic):
    """What an update run builds on: (previous_run, base_run, since_date).
    Refuses when there is no full run, or when the topic's query has changed
    since (an update would then mix two different scopes)."""
    prev = latest_run(data_dir, topic.name, modes={"full", "update"})
    if prev is None:
        raise SystemExit(f"no full fetch for {topic.name!r} yet, so there is nothing to update. "
                         f"Run a full fetch first: python -m pubmed_scraper fetch {topic.name}")
    pm = read_manifest(prev)
    if pm["query"] != topic.full_query:
        raise SystemExit(f"the query for {topic.name!r} in topics.toml has changed since run "
                         f"{prev.name}. An update would mix two different scopes; run a full "
                         f"fetch instead.")
    base_run = prev.name if mode_of(pm) == "full" else pm["base_run"]
    since = date.fromisoformat(pm["started_at"][:10]) - UPDATE_OVERLAP
    return prev, base_run, since


def choose_auto(data_dir, topic, log=print):
    """For --auto: update when there is a full run to build on and the query
    is unchanged since; otherwise a full fetch. Returns True for update."""
    prev = latest_run(data_dir, topic.name, modes={"full", "update"})
    if prev is None:
        log(f"auto: no full fetch for {topic.name!r} yet, so doing a full fetch")
        return False
    if read_manifest(prev)["query"] != topic.full_query:
        log(f"auto: the query in topics.toml changed since run {prev.name}, so doing a full fetch")
        return False
    log(f"auto: updating on top of run {prev.name}")
    return True


def fetch(topic, data_dir="data", limit=None, update=False, auto=False, batch_size=200,
          sort="pub_date", client=None, log=print):
    if sum(map(bool, (limit, update, auto))) > 1:
        raise SystemExit("choose only one of --limit, --update and --auto")
    if auto:
        update = choose_auto(data_dir, topic, log)
    client = client or EUtils()
    if not client.email:
        log("note: NCBI_EMAIL is not set. Add it to .env (see .env.example); "
            "NCBI asks every client to send a contact email.")

    started = datetime.now(timezone.utc)
    today = started.date()
    extra = {}

    if update:
        prev, base_run, since = plan_update(data_dir, topic)
        start, end, datetype = since, today + timedelta(days=1), "mdat"
        total = client.esearch_count(topic.full_query, _fmt(start), _fmt(end), datetype)
        log(f"{topic.label}: {total:,} matching papers added or changed since {since} "
            f"(update on top of {base_run})")
        mode = "update"
        extra = {"base_run": base_run, "previous_run": prev.name, "since": since.isoformat(),
                 "datetype": datetype}
    else:
        total = client.esearch_count(topic.full_query)
        log(f"{topic.label}: {total:,} matching papers in PubMed")
        mode = "sample" if limit else "full"

    run_dir = Path(data_dir) / "raw" / topic.name / started.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)

    if limit:
        pmids = client.esearch_ids(topic.full_query, retmax=min(limit, ESEARCH_CAP), sort=sort)
    elif update:
        pmids = collect_pmids(client, topic.full_query, start, end, datetype, log)
    else:
        pmids = collect_pmids(client, topic.full_query, FULL_START,
                              date(today.year + 5, 12, 31), "pdat", log)
        if len(pmids) < total:
            log(f"warning: PubMed reports {total:,} matches but only {len(pmids):,} PMIDs were "
                f"collected; papers with an unusual publication date may be missing")
    log(f"fetching {len(pmids):,} records ({mode}) into {run_dir}")

    (run_dir / "pmids.txt").write_text("".join(p + "\n" for p in pmids), encoding="utf-8")
    files, records = [], 0
    for b, i in enumerate(range(0, len(pmids), batch_size), 1):
        batch = pmids[i:i + batch_size]
        url, body = client.efetch_xml(batch)
        path = run_dir / f"efetch-{b:05d}.xml"
        path.write_bytes(body)
        n = body.count(b"<PubmedArticle>") + body.count(b"<PubmedBookArticle>")
        records += n
        files.append({"file": path.name, "url": url, "pmids_requested": len(batch),
                      "records_returned": n, "bytes": path.stat().st_size,
                      "sha256": _sha256(path)})
        log(f"  batch {b}: {n}/{len(batch)} records")

    if records != len(pmids):
        log(f"warning: requested {len(pmids):,} PMIDs but received {records:,} records")

    manifest = {
        "topic": topic.name,
        "label": topic.label,
        "query": topic.full_query,
        "mode": mode,
        **extra,
        "total_matching": total,
        "sample_limit": limit,
        "sort": sort if limit else None,
        "pmids_requested": len(pmids),
        "records_returned": records,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scraper_version": __version__,
        "files": files,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"done: {records:,} records saved")
    return run_dir
