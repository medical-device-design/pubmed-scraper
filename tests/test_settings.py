"""Tests for the .env settings reader.
Run from the repo root: python -m unittest discover -s tests"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pubmed_scraper import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text(
            "# comment\n"
            "\n"
            "NCBI_EMAIL=you@example.edu\n"
            'NCBI_API_KEY="abc123"\n'
            "NCBI_TOOL = my-tool \n"
            "not a setting\n",
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_values_and_strips_quotes(self):
        v = settings.read_env_file(self.env)
        self.assertEqual(v, {"NCBI_EMAIL": "you@example.edu", "NCBI_API_KEY": "abc123",
                             "NCBI_TOOL": "my-tool"})

    def test_missing_file_is_empty(self):
        self.assertEqual(settings.read_env_file(Path(self.tmp.name) / "nope"), {})

    def test_folder_named_env_is_ignored(self):
        folder = Path(self.tmp.name) / "env-folder"
        folder.mkdir()
        self.assertEqual(settings.read_env_file(folder), {})

    def test_environment_variable_wins(self):
        with mock.patch.dict(os.environ, {"NCBI_EMAIL": "override@example.edu"}):
            self.assertEqual(settings.get("NCBI_EMAIL", path=self.env), "override@example.edu")
        with mock.patch.dict(os.environ, {"NCBI_EMAIL": ""}):
            self.assertEqual(settings.get("NCBI_EMAIL", path=self.env), "you@example.edu")
        self.assertEqual(settings.get("MISSING", "dflt", path=self.env), "dflt")


if __name__ == "__main__":
    unittest.main()
