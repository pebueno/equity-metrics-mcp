# EquityMetrics MCP

Curated quarterly KPI estimates for public companies, served through a web chat
experience and an MCP server backed by PostgreSQL.

This README grows with each milestone. See `INSTRUCTIONS.md` for the full build
plan; the final version of this file will carry the architecture diagram,
decision rationale, MCP client setup, AI-use disclosure, and future work.

## Repository layout

| Path | Purpose |
| --- | --- |
| `backend/` | FastAPI application, shared KPI services, importer, and MCP server. |
| `web/` | React + TypeScript investor chat UI (Vite). |
| `docker-compose.yml` | PostgreSQL, API, and web services for local runs. |
| `kpi_sample_2000__282_29__281_29.csv` | Source dataset and import contract. |

## Configuration

Copy `.env.example` to `.env` and adjust. It documents every environment
variable the stack reads, including the PostgreSQL credentials and the LLM
provider settings. `LLM_PROVIDER=mock` is the default and requires no
credentials, so the application and its tests run offline.

## Running locally

### Everything, via Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

The API listens on <http://localhost:8000> and the web app on
<http://localhost:5173>.

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head          # needs PostgreSQL: docker compose up -d db
uvicorn equity_metrics.api.main:app --reload
```

Checks:

```bash
ruff format . && ruff check . && mypy && pytest
```

Tests that need PostgreSQL skip with an explanatory message when no server is
reachable, so `pytest` is always runnable. They use a separate
`equity_metrics_test` database, created automatically, and never touch
development data. Override the server with `TEST_DATABASE_URL`.

### Importing the dataset

```bash
cd backend
equity-import ../kpi_sample_2000__282_29__281_29.csv
```

The importer validates each row, rejects malformed ones without stopping, and
upserts on the source identity `(company, KPI, period, estimate_type, as_of)`.
Running it twice leaves the database unchanged. Add `--strict` to exit non-zero
when any row is rejected, or `--database-url` to target another database.

### Web

```bash
cd web
npm install
npm run dev
```

Checks:

```bash
npm run format:check && npm run lint && npm run test && npm run build
```

## HTTP API

All endpoints read through the shared `kpi_service` layer, which the MCP tools
will also use, so validation and SQL exist in one place.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Liveness. |
| `GET /api/sectors` | Sectors with company counts. |
| `GET /api/companies?query=&sector=&limit=` | Bounded company search. |
| `GET /api/companies/{company}/kpis` | Resolved company and the KPIs it reports. |
| `GET /api/companies/{company}/kpis/{kpi}/estimates?periods=` | Historical estimates, chronological. |
| `GET /api/companies/{company}/kpis/{kpi}/qtd` | Latest QTD snapshot, by greatest `as_of`. |

`{company}` accepts a ticker or an exact company name. Resolution is exact
ticker first, then exact normalized name; a substring match is never promoted
to a resolution, so the caller is never silently given the wrong company.

Recoverable failures return a stable body — `code`, `message`,
`normalized_query`, and up to five `suggestions` — with `404` for unknown
entities, `409` for input resembling several known entities, and `400` for a
malformed fiscal period.

Estimate values are JSON strings so exact decimal precision survives the wire,
and every value travels with its unit.

## Status

| Milestone | State |
| --- | --- |
| 0 — Bootstrap and conventions | Done |
| 1 — Data import and schema | Done |
| 2 — Shared KPI services and HTTP API | Done |
| 3 — MCP server and audit trail | Next |
| 4 — AI gateway | Pending |
| 5 — Investor chat UI | Pending |
| 6 — Integration, documentation, and handoff | Pending |
