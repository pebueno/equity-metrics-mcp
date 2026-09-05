"""Command-line entry point for the CSV importer."""

import argparse
import logging
import sys
from pathlib import Path

from equity_metrics.config import get_settings
from equity_metrics.db.session import build_engine, session_scope
from equity_metrics.importer.csv_import import ImportReport, MissingColumnsError, import_csv

logger = logging.getLogger("equity_metrics.importer")

MAX_REPORTED_ERRORS = 20


def main(argv: list[str] | None = None) -> int:
    """Import a CSV file into the configured database and report totals."""
    parser = argparse.ArgumentParser(description="Import KPI estimates from a CSV file.")
    parser.add_argument("csv_path", type=Path, help="Path to the source CSV file.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL for this run.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any row was rejected.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s %(message)s")

    if not args.csv_path.is_file():
        logger.error("CSV file not found: %s", args.csv_path)
        return 2

    engine = build_engine(args.database_url or settings.database_url)
    try:
        with session_scope(engine) as session:
            report = import_csv(args.csv_path, session)
    except MissingColumnsError as exc:
        logger.error("%s", exc)
        return 2
    finally:
        engine.dispose()

    _log_report(report)
    return 1 if args.strict and report.rows_rejected else 0


def _log_report(report: ImportReport) -> None:
    logger.info("import complete: %s", report.summary())
    for error in report.errors[:MAX_REPORTED_ERRORS]:
        logger.warning("line %d rejected (%s): %s", error.line_number, error.field, error.message)
    remaining = len(report.errors) - MAX_REPORTED_ERRORS
    if remaining > 0:
        logger.warning("%d further rejected rows not shown", remaining)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
