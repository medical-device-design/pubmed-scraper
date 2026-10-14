"""Entry point: python -m pubmed_scraper ..."""

import sys

if sys.version_info < (3, 11):
    sys.exit(f"pubmed-scraper needs Python 3.11 or newer (this is {sys.version.split()[0]}).")

from .cli import main  # noqa: E402

sys.exit(main())
