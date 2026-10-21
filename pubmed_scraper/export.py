"""Write parsed records as a dataset: one JSONL with everything, plus flat CSV
tables shaped for knowledge-graph loading (one row per node or edge).

    data/processed/<topic>/<run>/
        papers.jsonl     full nested record per paper
        papers.csv       one row per paper
        authors.csv      one row per (paper, author)
        mesh.csv         one row per (paper, MeSH descriptor)
        grants.csv       one row per (paper, grant)
        entities.csv     one row per (paper, PubTator3 entity)     if annotated
        relations.csv    one row per (paper, PubTator3 relation)   if annotated
        summary.json     counts, and the manifests of the raw runs it came from

Records are written as they arrive (streaming), so memory use does not grow
with the size of the run. CSVs are UTF-8 with a byte-order mark so Excel
opens them correctly.
"""

import csv
import json
from contextlib import ExitStack
from pathlib import Path

_J = "; "   # separator for multi-valued cells

PAPER_FIELDS = [
    "pmid", "topic", "title", "pub_year", "pub_date", "journal", "doi", "pmcid",
    "publication_types", "major_mesh", "keywords", "has_abstract", "is_retracted",
    "nct_ids", "nct_ids_in_text", "fda_numbers", "grant_count", "author_count", "first_author",
]
AUTHOR_FIELDS = ["pmid", "position", "name", "last_name", "fore_name", "orcid", "affiliation"]
MESH_FIELDS = ["pmid", "mesh_ui", "mesh_term", "major_topic", "qualifiers"]
GRANT_FIELDS = ["pmid", "grant_id", "agency", "country"]
ENTITY_FIELDS = ["pmid", "entity_type", "identifier", "database", "name", "mention_count",
                 "in_title", "is_normalized", "mentions"]
RELATION_FIELDS = ["pmid", "relation_type", "score", "entity1_type", "entity1_id", "entity1_name",
                   "entity2_type", "entity2_id", "entity2_name"]
COUNTS = {   # summary.json counter -> test on a record
    "with_abstract": lambda r: bool(r["abstract"]),
    "with_doi": lambda r: bool(r["doi"]),
    "in_pmc": lambda r: bool(r["pmcid"]),
    "with_grant": lambda r: bool(r["grants"]),
    "with_nct_id": lambda r: bool(r["nct_ids"]),
    "with_nct_id_in_text": lambda r: bool(r["nct_ids_in_text"]),
    "with_fda_number": lambda r: bool(r["fda_numbers"]),
    "retracted": lambda r: r["is_retracted"],
}


def author_name(au):
    if au.get("collective_name"):
        return au["collective_name"]
    parts = [au.get("fore_name") or au.get("initials"), au.get("last_name")]
    return " ".join(p for p in parts if p) or None


def paper_row(r, topic):
    return {
        "pmid": r["pmid"],
        "topic": topic,
        "title": r["title"],
        "pub_year": r["pub_year"],
        "pub_date": r["pub_date"],
        "journal": r["journal"],
        "doi": r["doi"],
        "pmcid": r["pmcid"],
        "publication_types": _J.join(filter(None, r["publication_types"])),
        "major_mesh": _J.join(m["term"] for m in r["mesh"] if m["major"] and m["term"]),
        "keywords": _J.join(r["keywords"]),
        "has_abstract": bool(r["abstract"]),
        "is_retracted": r["is_retracted"],
        "nct_ids": _J.join(r["nct_ids"]),
        "nct_ids_in_text": _J.join(r["nct_ids_in_text"]),
        "fda_numbers": _J.join(r["fda_numbers"]),
        "grant_count": len(r["grants"]),
        "author_count": len(r["authors"]),
        "first_author": author_name(r["authors"][0]) if r["authors"] else None,
    }


def author_rows(r):
    for i, au in enumerate(r["authors"], 1):
        yield {
            "pmid": r["pmid"],
            "position": i,
            "name": author_name(au),
            "last_name": au["last_name"],
            "fore_name": au["fore_name"],
            "orcid": au["orcid"],
            "affiliation": _J.join(au["affiliations"]),
        }


def mesh_rows(r):
    for m in r["mesh"]:
        yield {
            "pmid": r["pmid"],
            "mesh_ui": m["ui"],
            "mesh_term": m["term"],
            "major_topic": m["major"],
            "qualifiers": _J.join(q["term"] for q in m["qualifiers"] if q["term"]),
        }


def grant_rows(r):
    for g in r["grants"]:
        if g.get("id") or g.get("agency"):
            yield {"pmid": r["pmid"], "grant_id": g.get("id"), "agency": g.get("agency"),
                   "country": g.get("country")}


def _csv(stack, path, fields):
    f = stack.enter_context(open(path, "w", newline="", encoding="utf-8-sig"))
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    return w


def export(records, out_dir, topic, sources, stats, annotations=None, ann_stats=None):
    """Write every record from the `records` iterable, and every
    (pmid, entities, relations) from `annotations` when given. `stats` and
    `ann_stats` are the dicts the parsers fill in while they are consumed;
    they are read after the loops finish. `sources` is the list of raw-run
    manifests the data came from."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("entities.csv", "relations.csv"):     # from an earlier parse with annotations
        if annotations is None and (out / stale).exists():
            (out / stale).unlink()
    counts = dict.fromkeys(COUNTS, 0)
    ann_counts = {"entity_rows": 0, "normalized_entity_rows": 0, "relation_rows": 0}

    with ExitStack() as stack:
        jsonl = stack.enter_context(open(out / "papers.jsonl", "w", encoding="utf-8"))
        papers = _csv(stack, out / "papers.csv", PAPER_FIELDS)
        authors = _csv(stack, out / "authors.csv", AUTHOR_FIELDS)
        mesh = _csv(stack, out / "mesh.csv", MESH_FIELDS)
        grants = _csv(stack, out / "grants.csv", GRANT_FIELDS)

        for r in records:
            jsonl.write(json.dumps({"topic": topic, **r}, ensure_ascii=False) + "\n")
            papers.writerow(paper_row(r, topic))
            authors.writerows(author_rows(r))
            mesh.writerows(mesh_rows(r))
            grants.writerows(grant_rows(r))
            for key, test in COUNTS.items():
                counts[key] += 1 if test(r) else 0

        if annotations is not None:
            entities = _csv(stack, out / "entities.csv", ENTITY_FIELDS)
            relations = _csv(stack, out / "relations.csv", RELATION_FIELDS)
            for _pmid, ents, rels in annotations:
                for e in ents:
                    entities.writerow({**e, "mentions": _J.join(e["mentions"])})
                    ann_counts["entity_rows"] += 1
                    ann_counts["normalized_entity_rows"] += 1 if e["is_normalized"] else 0
                relations.writerows(rels)
                ann_counts["relation_rows"] += len(rels)

    summary = {**stats, **counts}
    if annotations is not None:
        summary["pubtator"] = {**(ann_stats or {}), **ann_counts}
    summary["runs"] = [s.get("run") for s in sources]
    summary["sources"] = sources
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
