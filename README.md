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

## MCP server

Four tools cover the natural agent workflow, all built on the same
`kpi_service` layer the HTTP API uses.

| Tool | Purpose |
| --- | --- |
| `search_companies(query, sector?)` | Candidates with canonical name, ticker, and sector. |
| `list_company_kpis(ticker_or_company)` | Resolved company and the KPIs it reports, with units. |
| `get_kpi_estimates(ticker, kpi, periods?)` | Historical estimates, chronological. |
| `get_qtd_estimate(ticker, kpi)` | Latest QTD snapshot, by greatest `as_of`. |

Run it over stdio:

```bash
cd backend
equity-mcp
```

Register it with an MCP client, using absolute paths:

```json
{
  "mcpServers": {
    "equity-metrics": {
      "command": "C:/path/to/equity-metrics-mcp/backend/.venv/Scripts/equity-mcp.exe",
      "env": {
        "DATABASE_URL": "postgresql+psycopg://equity:equity@localhost:5432/equity_metrics"
      }
    }
  }
}
```

On macOS or Linux the command is `.venv/bin/equity-mcp`. The database must be
running and imported first.

### Errors and auditing

A recoverable failure is a tool *result* with `isError` set, never a protocol
error, so an agent can correct itself and retry. The payload carries `code`
(`unknown_company`, `ambiguous_company`, `unknown_kpi`, `ambiguous_kpi`,
`invalid_period`, `no_data`), the normalized query, and up to five suggestions.

Every call writes one `mcp_tool_calls` row in a `finally` path, through its own
session so a rolled-back read cannot take the audit trail with it. The row holds
the tool, sanitized and bounded arguments, outcome, error code, duration, and a
correlation ID shared by all calls made for a single question. Credential- and
prompt-bearing argument names are redacted before storage.

## AI gateway

`backend/src/equity_metrics/ai_gateway/` isolates every provider concern behind
one interface — `answer(question, context) -> AgentResponse` — so a future
standalone deployment can keep the same contract. It is a module, not a service.

The gateway never queries PostgreSQL. It reaches data only through the MCP
tools, which keeps the database behind a single authoritative interface.

Guardrails on every answer:

| Guardrail | Setting | Default |
| --- | --- | --- |
| Tool iterations | `LLM_MAX_TOOL_ITERATIONS` | 6 |
| Per-provider-call timeout | `LLM_TIMEOUT_SECONDS` | 30 |
| Total answer budget | `LLM_TOTAL_TIMEOUT_SECONDS` | 90 |
| Retries, transient faults only | `LLM_MAX_RETRIES` | 2 |
| Tool response size | `MAX_TOOL_RESULT_CHARS` in code | 20,000 chars |

A permanent provider failure is never retried, because a rejected request fails
identically the second time.

### Providers

`LLM_PROVIDER=mock` is the default and needs no credential: it plans a tool
sequence from the question, recovers from a recoverable tool error by retrying
with the suggestion the tool offered, and writes its answer only from what the
tools returned. The same question always produces the same trace and the same
words, so the whole test suite runs offline.

`LLM_PROVIDER=anthropic` enables the live adapter. It requires `LLM_API_KEY` and
`pip install anthropic`, which is an optional dependency; without a key the
gateway refuses to build rather than falling back silently.

### Chat endpoint

`POST /api/chat` takes `{"question": "..."}` and returns the answer, a request
ID, the provider, model, and prompt version, the ordered tool trace — each entry
with its index, tool, sanitized arguments, status, error code, and duration —
and `data`, the structured payloads of the successful tool calls. The request ID
is the correlation ID on the `mcp_tool_calls` rows the answer produced, so the
visible trace and the audit trail line up.

`data` exists so the UI can render the figures as tables rather than parsing
them back out of prose. The sentence and the table come from the same tool call
and cannot disagree.

## Chat UI

One screen, no navigation: header, suggested prompts, conversation, composer.
Each answer carries the prose reply, a data panel, and a collapsed activity
panel.

- Values are shown with their units, dates and figures in tabular numerals so
  columns line up, and quarter-to-date results carry a visible QTD badge that
  distinguishes them from history.
- The activity panel expands to every tool call in order with its sanitized
  arguments, outcome or error code, and duration, plus the request ID, model,
  and prompt version. A recovered failure stays visible there even though it is
  kept out of the answer.
- Enter submits, Shift+Enter adds a line. Loading, service failure, and network
  failure each have their own state, and wide tables scroll inside their card so
  the page never scrolls sideways.

## Status

| Milestone | State |
| --- | --- |
| 0 — Bootstrap and conventions | Done |
| 1 — Data import and schema | Done |
| 2 — Shared KPI services and HTTP API | Done |
| 3 — MCP server and audit trail | Done |
| 4 — AI gateway | Done |
| 5 — Investor chat UI | Done |
| 6 — Integration, documentation, and handoff | Next |
