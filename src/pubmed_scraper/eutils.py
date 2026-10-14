"""Minimal NCBI E-utilities client: rate limiting, retries, and NCBI's usage rules.

NCBI policy (https://www.ncbi.nlm.nih.gov/books/NBK25497/):
  * at most 3 requests/second without an API key, 10/second with one
  * send `tool` and `email` with every request
  * run large jobs on weekends or 9 PM - 5 AM US Eastern on weekdays

Configure with environment variables:
  NCBI_EMAIL    contact email for the developer (strongly recommended)
  NCBI_API_KEY  raises the limit to 10 requests/second (optional)
  NCBI_TOOL     tool name sent to NCBI (default: pubmed-scraper)
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
USER_AGENT = f"pubmed-scraper/{__version__} (medical-device-design)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class EUtils:
    def __init__(self, email=None, api_key=None, tool=None, timeout=120):
        self.email = email if email is not None else os.environ.get("NCBI_EMAIL", "")
        self.api_key = api_key if api_key is not None else os.environ.get("NCBI_API_KEY", "")
        self.tool = tool or os.environ.get("NCBI_TOOL", "pubmed-scraper")
        self.timeout = timeout
        self.min_interval = 0.11 if self.api_key else 0.34
        self._last = 0.0

    def _params(self, params):
        p = {"tool": self.tool, **params}
        if self.email:
            p["email"] = self.email
        if self.api_key:
            p["api_key"] = self.api_key
        return p

    def _wait(self):
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def request(self, util, params, post=False, retries=4):
        """GET (or POST, for long ID lists) one E-utility. Returns (url, bytes).
        The returned URL never includes the API key, so it is safe to log."""
        params = self._params(params)
        safe_url = BASE + util + "?" + urllib.parse.urlencode(
            {k: v for k, v in params.items() if k != "api_key" and not (post and k == "id")})
        url = BASE + util
        data = None
        if post:
            data = urllib.parse.urlencode(params).encode()
        else:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(retries + 1):
            self._wait()
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return safe_url, r.read()
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES or attempt == retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == retries:
                    raise
            time.sleep(2 ** attempt)        # 1, 2, 4, 8 s

    # ------------------------------------------------------------------
    def esearch_count(self, term, mindate=None, maxdate=None):
        p = {"db": "pubmed", "term": term, "rettype": "count", "retmode": "json"}
        if mindate:
            p.update(datetype="pdat", mindate=mindate, maxdate=maxdate)
        _, body = self.request("esearch.fcgi", p)
        return int(json.loads(body)["esearchresult"]["count"])

    def esearch_ids(self, term, retmax, sort=None, mindate=None, maxdate=None):
        p = {"db": "pubmed", "term": term, "retmode": "json", "retmax": str(retmax)}
        if sort:
            p["sort"] = sort
        if mindate:
            p.update(datetype="pdat", mindate=mindate, maxdate=maxdate)
        _, body = self.request("esearch.fcgi", p)
        return json.loads(body)["esearchresult"]["idlist"]

    def efetch_xml(self, pmids):
        """Full PubMed XML for a batch of PMIDs (sent as POST)."""
        return self.request("efetch.fcgi",
                            {"db": "pubmed", "retmode": "xml", "id": ",".join(pmids)},
                            post=True)
