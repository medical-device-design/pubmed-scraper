# pubmed-scraper
A data scraper for getting information for Knowledge Graph building

Collects PubMed papers on medical-device research by research type (in vitro
first; in vivo, safety and effectiveness planned) through NCBI's E-utilities,
and turns them into tables ready for loading into the medical-device-kg graph.

## Setup

Needs [uv](https://docs.astral.sh/uv/). No other dependencies.

Set a contact email (NCBI asks every client to send one). An API key is
optional and raises the rate limit from 3 to 10 requests per second.

```powershell
$env:NCBI_EMAIL = "you@hofstra.edu"
$env:NCBI_API_KEY = "..."        # optional, from your NCBI account settings
```

## Usage

```powershell
uv run pubmed-scraper topics                       # list topics and their queries
uv run pubmed-scraper count in_vitro               # papers matching a topic
uv run pubmed-scraper fetch in_vitro --limit 200   # sample: 200 most recent
uv run pubmed-scraper fetch in_vitro               # everything matching
uv run pubmed-scraper parse in_vitro               # latest fetch -> tables
```

Queries live in `topics.toml`. Each topic's query is combined with the shared
device filter as `(device_filter) AND (topic)`.

NCBI asks that large jobs run on weekends or 9 PM to 5 AM US Eastern.

## Output

```
data/raw/<topic>/<run>/          untouched PubMed XML, PMID list, manifest.json
data/processed/<topic>/<run>/
    papers.jsonl                 everything per paper, nested
    papers.csv                   one row per paper
    authors.csv                  one row per (paper, author)
    mesh.csv                     one row per (paper, MeSH term)
    summary.json                 counts and the source manifest
```

Raw files are kept so data can be re-parsed without contacting NCBI again.
A raw run without `manifest.json` did not finish and is ignored by `parse`.
`data/` is git-ignored.

`papers.jsonl` includes abstracts. Abstracts can be under publisher copyright,
so keep them out of anything published openly (such as the graph on the
Proto-OKN Fabric).

## Tests

```powershell
uv run python -m unittest discover -s tests
```
