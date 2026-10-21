"""Minimal NCBI E-utilities client: rate limiting, retries, and NCBI's usage rules.

NCBI policy (https://www.ncbi.nlm.nih.gov/books/NBK25497/):
  * at most 3 requests/second without an API key, 10/second with one
  * send `tool` and `email` with every request
  * run large jobs on weekends or 9 PM - 5 AM US Eastern on weekdays

Configure in the repo's .env file (see .env.example) or as environment variables:
  NCBI_EMAIL    contact email for the developer (strongly recommended)
  NCBI_API_KEY  raises the limit to 10 requests/second (optional)
  NCBI_TOOL     tool name sent to NCBI (default: pubmed-scraper)
"""

import json
import urllib.parse

from . import settings
from .net import Http

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


class EUtils:
    def __init__(self, email=None, api_key=None, tool=None, timeout=120):
        self.email = email if email is not None else settings.get("NCBI_EMAIL")
        self.api_key = api_key if api_key is not None else settings.get("NCBI_API_KEY")
        self.tool = tool or settings.get("NCBI_TOOL") or "pubmed-scraper"
        self.http = Http(min_interval=0.11 if self.api_key else 0.34, timeout=timeout)

    def _params(self, params):
        p = {"tool": self.tool, **params}
        if self.email:
            p["email"] = self.email
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def request(self, util, params, post=False):
        """GET (or POST, for long ID lists) one E-utility. Returns (url, bytes).
        The returned URL leaves out the API key and email, so it is safe to log
        and to store in manifests that may be shared."""
        params = self._params(params)
        safe_url = BASE + util + "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items()
             if k not in ("api_key", "email") and not (post and k == "id")})
        if post:
            body = self.http.open(BASE + util, data=urllib.parse.urlencode(params).encode())
        else:
            body = self.http.open(BASE + util + "?" + urllib.parse.urlencode(params))
        return safe_url, body

    # ------------------------------------------------------------------
    # datetype: "pdat" publication date, "mdat" date the record last changed,
    # "edat" date the record entered PubMed. Dates are YYYY/MM/DD.
    def esearch_count(self, term, mindate=None, maxdate=None, datetype="pdat"):
        p = {"db": "pubmed", "term": term, "rettype": "count", "retmode": "json"}
        if mindate:
            p.update(datetype=datetype, mindate=mindate, maxdate=maxdate)
        _, body = self.request("esearch.fcgi", p)
        return int(json.loads(body)["esearchresult"]["count"])

    def esearch_ids(self, term, retmax, sort=None, mindate=None, maxdate=None, datetype="pdat"):
        p = {"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax)}
        if sort:
            p["sort"] = sort
        if mindate:
            p.update(datetype=datetype, mindate=mindate, maxdate=maxdate)
        _, body = self.request("esearch.fcgi", p)
        return json.loads(body)["esearchresult"]["idlist"]

    def efetch_xml(self, pmids):
        """Full PubMed XML for a batch of PMIDs (sent as POST)."""
        return self.request("efetch.fcgi",
                            {"db": "pubmed", "retmode": "xml", "id": ",".join(pmids)},
                            post=True)
