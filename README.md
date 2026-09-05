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
uvicorn equity_metrics.api.main:app --reload
```

Checks:

```bash
ruff format . && ruff check . && mypy && pytest
```

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

## Status

| Milestone | State |
| --- | --- |
| 0 — Bootstrap and conventions | Done |
| 1 — Data import and schema | Next |
| 2 — Shared KPI services and HTTP API | Pending |
| 3 — MCP server and audit trail | Pending |
| 4 — AI gateway | Pending |
| 5 — Investor chat UI | Pending |
| 6 — Integration, documentation, and handoff | Pending |
