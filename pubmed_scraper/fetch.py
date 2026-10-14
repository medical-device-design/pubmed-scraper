"""Search PubMed for a topic and save the raw records, untouched, to disk.

Each run writes a new folder:

    data/raw/<topic>/<YYYYMMDD-HHMMSS>/
        pmids.txt            every PMID requested, one per line
        efetch-00001.xml     raw PubMed XML, one file per batch
        manifest.json        query, counts, checksums; written LAST

Parsing works only from these saved files, so the data can be re-processed
without contacting NCBI again. A run with no manifest.json did not finish and
is ignored by `parse`.
"""

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import __version__
from .eutils import EUtils

ESEARCH_CAP = 9999      # ESearch cannot return more than 10,000 PubMed IDs per query
FIRST_YEAR = 1800


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def date_windows(client, term, y0, y1, log=print):
    """Yield (mindate, maxdate) publication-date windows that each hold at most
    ESEARCH_CAP records: halve year ranges, then split a single year by month."""
    n = client.esearch_count(term, f"{y0}/01/01", f"{y1}/12/31")
    if n == 0:
        return
    if n <= ESEARCH_CAP:
        yield f"{y0}/01/01", f"{y1}/12/31"
        return
    if y0 < y1:
        mid = (y0 + y1) // 2
        yield from date_windows(client, term, y0, mid, log)
        yield from date_windows(client, term, mid + 1, y1, log)
        return
    for m in range(1, 13):
        nxt = date(y0 + (m == 12), m % 12 + 1, 1)
        last = (nxt - date.resolution).day
        lo, hi = f"{y0}/{m:02d}/01", f"{y0}/{m:02d}/{last:02d}"
        k = client.esearch_count(term, lo, hi)
        if k > ESEARCH_CAP:
            raise RuntimeError(f"{k} records in {y0}-{m:02d} alone; narrow the query")
        if k:
            yield lo, hi


def collect_pmids(client, term, limit=None, sort="pub_date", log=print):
    """PMIDs matching term. With limit: the first `limit` in `sort` order (one
    request). Without: every match, gathered window by window."""
    if limit:
        return client.esearch_ids(term, retmax=min(limit, ESEARCH_CAP), sort=sort)
    pmids = set()
    for lo, hi in date_windows(client, term, FIRST_YEAR, date.today().year + 1, log):
        ids = client.esearch_ids(term, retmax=ESEARCH_CAP, mindate=lo, maxdate=hi)
        pmids.update(ids)
        log(f"  {lo} to {hi}: {len(ids):,} PMIDs (total so far {len(pmids):,})")
    return sorted(pmids, key=int)


def fetch(topic, data_dir="data", limit=None, batch_size=200, sort="pub_date",
          client=None, log=print):
    client = client or EUtils()
    if not client.email:
        log("note: NCBI_EMAIL is not set. Add it to .env (see .env.example); "
            "NCBI asks every client to send a contact email.")

    started = datetime.now(timezone.utc)
    run_dir = Path(data_dir) / "raw" / topic.name / started.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=False)

    total = client.esearch_count(topic.full_query)
    log(f"{topic.label}: {total:,} matching papers in PubMed")
    pmids = collect_pmids(client, topic.full_query, limit=limit, sort=sort, log=log)
    log(f"fetching {len(pmids):,} records{' (sample)' if limit else ''} into {run_dir}")

    (run_dir / "pmids.txt").write_text("\n".join(pmids) + "\n", encoding="utf-8")
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
