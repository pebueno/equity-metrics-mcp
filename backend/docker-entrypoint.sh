#!/bin/sh
# Bring the database to the current schema before serving, then optionally load
# the sample dataset. The importer is idempotent, so a restart is safe.
set -eu

echo "applying migrations"
alembic upgrade head

if [ "${IMPORT_ON_START:-false}" = "true" ]; then
  if [ -f "${CSV_PATH:-/data/kpi_sample.csv}" ]; then
    echo "importing ${CSV_PATH:-/data/kpi_sample.csv}"
    equity-import "${CSV_PATH:-/data/kpi_sample.csv}"
  else
    echo "IMPORT_ON_START is set but ${CSV_PATH:-/data/kpi_sample.csv} is missing" >&2
    exit 1
  fi
fi

exec "$@"
