"""Write parsed records as a dataset: one JSONL with everything, plus flat CSV
tables shaped for knowledge-graph loading (one row per node or edge).

    data/processed/<topic>/<run>/
        papers.jsonl     full nested record per paper
        papers.csv       one row per paper
        authors.csv      one row per (paper, author)
        mesh.csv         one row per (paper, MeSH descriptor)
        summary.json     counts, and the manifest of the raw run it came from

Records are written as they arrive (streaming), so memory use does not grow
with the size of the run. CSVs are UTF-8 with a byte-order mark so Excel
opens them correctly.
"""

import csv
import json
from contextlib import ExitStack
from pathlib import Path

_J = "; "   # separator for multi-valued cells in papers.csv

PAPER_FIELDS = [
    "pmid", "topic", "title", "pub_year", "pub_date", "journal", "doi", "pmcid",
    "publication_types", "major_mesh", "keywords", "has_abstract", "is_retracted",
    "nct_ids", "fda_numbers", "author_count", "first_author",
]
AUTHOR_FIELDS = ["pmid", "position", "name", "last_name", "fore_name", "orcid", "affiliation"]
MESH_FIELDS = ["pmid", "mesh_ui", "mesh_term", "major_topic", "qualifiers"]
COUNTS = {   # summary.json counter -> test on a record
    "with_abstract": lambda r: bool(r["abstract"]),
    "with_doi": lambda r: bool(r["doi"]),
    "in_pmc": lambda r: bool(r["pmcid"]),
    "with_nct_id": lambda r: bool(r["nct_ids"]),
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
        "fda_numbers": _J.join(r["fda_numbers"]),
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


def export(records, out_dir, topic, manifest, stats):
    """Write every record from the `records` iterable. `stats` is the dict the
    parser fills in while it is consumed; it is read after the loop finishes."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    counts = dict.fromkeys(COUNTS, 0)

    with ExitStack() as stack:
        def csv_writer(name, fields):
            f = stack.enter_context(open(out / name, "w", newline="", encoding="utf-8-sig"))
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            return w

        jsonl = stack.enter_context(open(out / "papers.jsonl", "w", encoding="utf-8"))
        papers = csv_writer("papers.csv", PAPER_FIELDS)
        authors = csv_writer("authors.csv", AUTHOR_FIELDS)
        mesh = csv_writer("mesh.csv", MESH_FIELDS)

        for r in records:
            jsonl.write(json.dumps({"topic": topic, **r}, ensure_ascii=False) + "\n")
            papers.writerow(paper_row(r, topic))
            authors.writerows(author_rows(r))
            mesh.writerows(mesh_rows(r))
            for key, test in COUNTS.items():
                counts[key] += 1 if test(r) else 0

    summary = {**stats, **counts, "source_manifest": manifest}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
