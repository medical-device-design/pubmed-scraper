"""Shared HTTP plumbing: an honest User-Agent, a minimum gap between requests,
and retries with backoff on rate-limit, server and network errors."""

import http.client
import sys
import time
import urllib.error
import urllib.request

from . import __version__

USER_AGENT = f"pubmed-scraper/{__version__} (medical-device-design)"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class Http:
    def __init__(self, min_interval, timeout=120, retries=6):
        self.min_interval = min_interval     # seconds between request starts
        self.timeout = timeout
        self.retries = retries
        self._last = 0.0

    def _wait(self):
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def open(self, url, data=None):
        """GET url (POST when data is given) and return the response body."""
        for attempt in range(self.retries + 1):
            self._wait()
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES or attempt == self.retries:
                    raise
                e.close()
                problem = f"HTTP {e.code}"
            # Connection dropped or timed out, before or during the response
            # (URLError, ConnectionResetError, TimeoutError, IncompleteRead, ...)
            except (OSError, http.client.HTTPException) as e:
                if attempt == self.retries:
                    raise
                problem = f"{type(e).__name__}: {e}"
            wait = 2 ** attempt             # 1, 2, 4, 8, 16, 32 s
            print(f"  network problem ({problem}); retrying in {wait} s", file=sys.stderr)
            time.sleep(wait)
