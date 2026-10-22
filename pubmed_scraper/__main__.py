"""Entry point: python -m pubmed_scraper ..."""

import sys

if sys.version_info < (3, 10):
    sys.exit(f"pubmed-scraper needs Python 3.10 or newer (this is {sys.version.split()[0]}).")

from .cli import main  # noqa: E402

sys.exit(main())
