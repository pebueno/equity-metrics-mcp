"""Input normalization shared by the importer and, later, entity resolution.

These helpers only prepare values for comparison and storage. The database
remains the single source of truth for what actually exists.
"""

import re

_WHITESPACE = re.compile(r"\s+")
_PERIOD = re.compile(r"^(?P<year>\d{4})Q(?P<quarter>[1-4])$")


def collapse_whitespace(value: str) -> str:
    """Trim the value and collapse internal whitespace runs to a single space."""
    return _WHITESPACE.sub(" ", value).strip()


def normalize_name(value: str) -> str:
    """Case-fold a company, sector, or KPI name for exact-match comparison."""
    return collapse_whitespace(value).casefold()


def normalize_ticker(value: str) -> str:
    """Return the canonical uppercase ticker form."""
    return collapse_whitespace(value).upper()


def is_valid_period(value: str) -> bool:
    """Return whether the label is a `YYYYQ[1-4]` fiscal period."""
    return _PERIOD.match(value) is not None
