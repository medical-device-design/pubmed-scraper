"""Tests for HTTP retries: which errors are retried and which are not. No network.
Run from the repo root: python -m unittest discover -s tests"""

import http.client
import io
import unittest
import urllib.error
from unittest import mock

from pubmed_scraper.net import Http


class Response(io.BytesIO):
    """Stands in for what urlopen returns (a context manager with .read())."""


def http_error(code):
    return urllib.error.HTTPError("https://example.org", code, "error", {}, io.BytesIO(b""))


class RetryTest(unittest.TestCase):
    def run_open(self, outcomes, retries=6):
        """Http.open against a fake urlopen that raises or returns `outcomes` in turn."""
        calls = iter(outcomes)

        def fake_urlopen(req, timeout):
            out = next(calls)
            if isinstance(out, BaseException):
                raise out
            return Response(out)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep") as sleep, mock.patch("sys.stderr", io.StringIO()) as err:
            try:
                return Http(min_interval=0, retries=retries).open("https://example.org"), sleep, err
            except Exception as e:
                return e, sleep, err

    def test_dropped_connections_are_retried(self):
        for problem in (ConnectionResetError("reset by peer"),
                        http.client.RemoteDisconnected("closed without response"),
                        http.client.IncompleteRead(b"partial", 100),
                        TimeoutError("timed out"),
                        urllib.error.URLError("name lookup failed"),
                        http_error(503)):
            body, sleep, err = self.run_open([problem, b"ok"])
            self.assertEqual(body, b"ok", msg=repr(problem))
            self.assertEqual(sleep.call_count, 1)
            self.assertIn("retrying in 1 s", err.getvalue())

    def test_client_errors_are_not_retried(self):
        result, sleep, _ = self.run_open([http_error(400), b"never reached"])
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertEqual(result.code, 400)
        sleep.assert_not_called()

    def test_gives_up_after_the_last_retry(self):
        result, sleep, _ = self.run_open([ConnectionResetError("reset")] * 4, retries=3)
        self.assertIsInstance(result, ConnectionResetError)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 4])


if __name__ == "__main__":
    unittest.main()
