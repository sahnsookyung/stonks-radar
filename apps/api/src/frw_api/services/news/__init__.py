"""News radar service helpers.

The public app reads published snapshots only. These helpers are deterministic
building blocks for server-side ingestion, review, scoring, and publication.
"""

from frw_api.services.news.snapshot_builder import news_symbol_key

__all__ = ["news_symbol_key"]
