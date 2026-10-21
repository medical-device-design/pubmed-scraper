"""PubTator3 entity annotations for fetched papers.

PubTator3 (NCBI) runs text mining over PubMed titles and abstracts and links
each mention to a standard identifier, so we don't have to parse text ourselves:

    Gene       NCBI Gene ID           e.g. 650 (BMP2)
    Disease    MeSH                   e.g. MESH:D001847 (Bone Diseases)
    Chemical   MeSH                   e.g. MESH:D014025 (Titanium)
    Species    NCBI Taxonomy          e.g. 9606 (human)
    Variant, CellLine                 tmVar / Cellosaurus IDs

It also extracts relations between entities (association, treatment, ...).

Raw output is saved inside the fetch run it belongs to:

    data/raw/<topic>/<run>/pubtator/
        batch-00001.json   raw BioC JSON for up to 100 papers (the API maximum)
        manifest.json      counts, PMIDs PubTator has no record of; written LAST

If an annotate run stops partway, running it again reuses the batch files
already saved and continues from there.

The raw files contain titles and abstracts, so they stay local like the rest
of data/raw. Only identifiers and counts go into the output tables.

API: https://www.ncbi.nlm.nih.gov/research/pubtator3/api  (no key needed).
Requests are kept to 3 per second at most. A batch of 100 takes several
seconds, so ~70,000 papers take roughly 1.5 hours.
"""

import hashlib
import json
import shutil
import time
import urllib.error
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .net import Http

API = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/publications/export/biocjson"
MAX_BATCH = 100
_NOT_FOUND = "Could not retrieve publications"   # 400 body when no PMID in a batch is known


class PubTator:
    def __init__(self, timeout=180):
        self.http = Http(min_interval=0.34, timeout=timeout)

    def export(self, pmids):
        """Raw BioC JSON bytes for up to 100 PMIDs. Returns an empty document
        list when PubTator3 knows none of them (it answers that with a 400)."""
        if len(pmids) > MAX_BATCH:
            raise ValueError(f"PubTator3 accepts at most {MAX_BATCH} PMIDs per request")
        url = API + "?" + urllib.parse.urlencode({"pmids": ",".join(pmids)})
        try:
            return url, self.http.open(url)
        except urllib.error.HTTPError as e:
            with e:
                body = e.read().decode("utf-8", "replace")
            if e.code == 400 and _NOT_FOUND in body:
                return url, b'{"PubTator3": []}'
            raise


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def doc_pmid(doc):
    return str(doc.get("pmid") or doc.get("id") or "").split("|")[0].strip()


def _read_batch(path):
    """Documents in a saved batch file, or None if the file is unusable
    (e.g. cut off when a previous run was interrupted)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    docs = data.get("PubTator3") if isinstance(data, dict) else None
    return docs if isinstance(docs, list) else None


def annotate(run_dir, client=None, force=False, log=print):
    """Download PubTator3 annotations for every PMID in a fetch run."""
    run_dir = Path(run_dir)
    out = run_dir / "pubtator"
    if (out / "manifest.json").is_file() and not force:
        log(f"  {run_dir.name}: already annotated (use --force to redo)")
        return out
    if force and out.exists():
        shutil.rmtree(out)
    out.mkdir(exist_ok=True)

    client = client or PubTator()
    pmids = [p.strip() for p in (run_dir / "pmids.txt").read_text(encoding="utf-8").splitlines()
             if p.strip()]
    batches = [pmids[i:i + MAX_BATCH] for i in range(0, len(pmids), MAX_BATCH)]
    log(f"  {run_dir.name}: annotating {len(pmids):,} papers in {len(batches):,} batches")

    started = datetime.now(timezone.utc)
    t0, fetched = time.monotonic(), 0
    files, missing, returned = [], [], 0
    for b, batch in enumerate(batches, 1):
        path = out / f"batch-{b:05d}.json"
        docs = _read_batch(path) if path.is_file() else None
        reused = docs is not None
        if not reused:
            url, body = client.export(batch)
            path.write_bytes(body)
            docs = _read_batch(path)
            if docs is None:
                raise RuntimeError(f"PubTator3 returned something that isn't BioC JSON for batch {b}")
            fetched += 1
        got = {doc_pmid(d) for d in docs}
        missing += [p for p in batch if p not in got]
        returned += len(got & set(batch))
        files.append({"file": path.name, "pmids_requested": len(batch),
                      "documents_returned": len(docs), "reused": reused,
                      "bytes": path.stat().st_size, "sha256": _sha256(path)})
        if fetched and (b % 10 == 0 or b == len(batches)):
            left = (len(batches) - b) * (time.monotonic() - t0) / fetched
            log(f"    batch {b}/{len(batches)}  ({returned:,} papers so far, ~{left / 60:.0f} min left)")

    manifest = {
        "source": "PubTator3",
        "api": API,
        "run": run_dir.name,
        "pmids_requested": len(pmids),
        "papers_returned": returned,
        "pmids_not_in_pubtator": missing,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scraper_version": __version__,
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"  {run_dir.name}: {returned:,} of {len(pmids):,} papers annotated"
        + (f"; {len(missing):,} not in PubTator3 yet (usually the newest papers)" if missing else ""))
    return out


# ===========================================================================
#  Parsing saved annotations (offline)
# ===========================================================================
def _entity_id(infons):
    """(identifier, database) when PubTator3 linked the mention to a standard
    ID, else (None, None)."""
    ident = infons.get("identifier")
    if not infons.get("valid") or ident in (None, "", "-"):
        return None, None
    return str(ident), infons.get("database")


def parse_doc(doc):
    """One PubTator3 document -> (pmid, entities, relations).

    Entities are aggregated per paper: one row per distinct entity, with how
    often and where it was mentioned. Mentions PubTator3 could not link to an
    identifier are kept too (is_normalized=False), grouped by their text,
    because they still carry information (e.g. material names like "GelMA")."""
    pmid = doc_pmid(doc)
    ents = {}
    for passage in doc.get("passages", []):
        section = (passage.get("infons") or {}).get("type") or ""
        for a in passage.get("annotations", []):
            inf = a.get("infons") or {}
            etype = inf.get("type") or ""
            mention = " ".join((a.get("text") or "").split())
            ident, db = _entity_id(inf)
            key = (etype, ident) if ident else (etype, "text:" + mention.lower())
            e = ents.get(key)
            if e is None:
                e = ents[key] = {"entity_type": etype, "identifier": ident, "database": db,
                                 "linked_name": inf.get("name") if ident else None,
                                 "mentions": Counter(), "in_title": False}
            e["mentions"][mention] += 1
            e["in_title"] |= section == "title"

    entities = []
    for e in ents.values():
        name = e["linked_name"]
        if not name or name == e["identifier"]:     # Species "name" is just the tax ID
            name = e["mentions"].most_common(1)[0][0] if e["mentions"] else None
        entities.append({
            "pmid": pmid,
            "entity_type": e["entity_type"],
            "identifier": e["identifier"],
            "database": e["database"],
            "name": name,
            "mention_count": sum(e["mentions"].values()),
            "in_title": e["in_title"],
            "is_normalized": e["identifier"] is not None,
            "mentions": sorted(e["mentions"]),
        })
    entities.sort(key=lambda r: (r["entity_type"], r["identifier"] or "", r["name"] or ""))

    relations = []
    raw_rels = list(doc.get("relations", []))
    for passage in doc.get("passages", []):
        raw_rels += passage.get("relations", [])
    for rel in raw_rels:
        inf = rel.get("infons") or {}
        r1, r2 = inf.get("role1") or {}, inf.get("role2") or {}
        try:
            score = float(inf["score"]) if inf.get("score") not in (None, "") else None
        except (TypeError, ValueError):
            score = None
        relations.append({
            "pmid": pmid,
            "relation_type": inf.get("type"),
            "score": score,
            "entity1_type": r1.get("type"),
            "entity1_id": r1.get("identifier"),
            "entity1_name": r1.get("name"),
            "entity2_type": r2.get("type"),
            "entity2_id": r2.get("identifier"),
            "entity2_name": r2.get("name"),
        })
    return pmid, entities, relations


def iter_annotations(run_dirs, stats):
    """(pmid, entities, relations) for every annotated paper in the given runs,
    newest run first, each PMID once (newest annotation wins). Runs without a
    finished pubtator/ folder are skipped and listed in stats."""
    stats.setdefault("papers_annotated", 0)
    stats.setdefault("runs_not_annotated", [])
    seen, missing = set(), set()
    for run_dir in sorted((Path(r) for r in run_dirs), key=lambda p: p.name, reverse=True):
        folder = run_dir / "pubtator"
        if not (folder / "manifest.json").is_file():
            stats["runs_not_annotated"].append(run_dir.name)
            continue
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        missing.update(m.get("pmids_not_in_pubtator", []))
        for path in sorted(folder.glob("batch-*.json")):
            for doc in _read_batch(path) or []:
                pmid = doc_pmid(doc)
                if not pmid or pmid in seen:
                    continue
                seen.add(pmid)
                stats["papers_annotated"] += 1
                yield parse_doc(doc)
    # papers no run could annotate (a paper missing in an old run may be
    # annotated in a newer one, so this is not just the sum of the manifests)
    stats["pmids_not_in_pubtator"] = len(missing - seen)
