"""Tests for reading topics.toml, including the Python 3.10 fallback reader.
Run from the repo root: python -m unittest discover -s tests"""

import unittest

from pubmed_scraper import toml_lite
from pubmed_scraper.config import load_topics
from pubmed_scraper.settings import TOPICS_FILE

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


class TomlLiteTest(unittest.TestCase):
    def test_reads_the_real_topics_file_like_tomllib(self):
        text = TOPICS_FILE.read_text(encoding="utf-8")
        lite = toml_lite.loads(text)
        self.assertEqual(lite["device_filter"]["query"], '"Equipment and Supplies"[MeSH Major Topic]')
        self.assertIn("in_vitro", lite["topics"])
        if tomllib:                                  # on 3.11+, compare with the standard reader
            self.assertEqual(lite, tomllib.loads(text))

    def test_strings_tables_and_comments(self):
        cfg = toml_lite.loads(
            "# top comment\n"
            "[a]\n"
            "lit = 'x \"quoted\" \\n stays'   # trailing comment\n"
            'basic = "tab\\there \\"q\\" back\\\\slash"\n'
            "[b.c]  # header comment\n"
            "hash = '# not a comment'\n")
        self.assertEqual(cfg, {"a": {"lit": 'x "quoted" \\n stays', "basic": 'tab\there "q" back\\slash'},
                               "b": {"c": {"hash": "# not a comment"}}})

    def test_unsupported_syntax_is_an_error_not_a_misread(self):
        for bad in ("[a]\nn = 3", "[a]\nl = ['x']", "[a]\nm = '''x'''", "[a]\nu = 'open",
                    "[a]\nk = 'x' junk", "[a]\nk = 'x'\nk = 'y'", "[[arr]]", "no equals sign"):
            with self.assertRaises(toml_lite.TOMLLiteError, msg=bad):
                toml_lite.loads(bad)

    def test_load_topics_builds_the_full_query(self):
        t = load_topics(TOPICS_FILE)["in_vitro"]
        self.assertEqual(t.full_query, f'("Equipment and Supplies"[MeSH Major Topic]) AND ({t.query})')


if __name__ == "__main__":
    unittest.main()
