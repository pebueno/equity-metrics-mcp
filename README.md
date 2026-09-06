# EquityMetrics MCP

Curated quarterly KPI estimates for public companies, served through a web chat
experience and an MCP server, both reading from PostgreSQL.

The database is the system of record. The language model explains what the tools
retrieved; it never supplies a company, KPI, fiscal period, value, unit, or
snapshot date of its own.

## Contents

- [Quick start](#quick-start)
- [Running each service directly](#running-each-service-directly)
- [Importing the dataset](#importing-the-dataset)
- [Tests and checks](#tests-and-checks)
- [Architecture](#architecture)
- [HTTP API](#http-api)
- [MCP server](#mcp-server)
- [AI gateway](#ai-gateway)
- [Chat UI](#chat-ui)
- [Decisions](#decisions)
- [LLM tool-calling failure modes](#llm-tool-calling-failure-modes)
- [Future improvements](#future-improvements)
- [Use of AI tools](#use-of-ai-tools)

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

That is the whole setup. The `api` container applies migrations and imports the
sample CSV before serving, and each service waits for the one below it to report
healthy, so the stack is usable as soon as it is up:

| Service | URL | Notes |
| --- | --- | --- |
| Web | <http://localhost:5173> | The investor chat UI. |
| API | <http://localhost:8000> | OpenAPI docs at `/docs`. |
| PostgreSQL | `localhost:5432` | Credentials from `.env`. |

The import is idempotent, so restarting the stack does not duplicate data. Set
`IMPORT_ON_START=false` to skip it.

`LLM_PROVIDER=mock` is the default and needs no credential, so a clean checkout
answers questions offline.

## Running each service directly

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

docker compose up -d db       # from the repository root
alembic upgrade head
uvicorn equity_metrics.api.main:app --reload
```

### Web

```bash
cd web
npm install
npm run dev
```

The dev server proxies `/api` to <http://localhost:8000>, so no CORS or base-URL
configuration is needed.

### Configuration

`.env.example` documents every variable the stack reads. Copy it to `.env` and
adjust; `.env` is never committed.

## Importing the dataset

```bash
cd backend
equity-import ../kpi_sample.csv
```

Each row is validated before it is stored: the fiscal period must match
`YYYYQ[1-4]`, `estimate_type` must be `historical` or `qtd`, a QTD row must carry
an `as_of` date, values must parse as decimals, and a KPI's unit must agree with
the unit already recorded for it. A malformed row is reported with its line
number and skipped; the rest of the file still imports.

Estimates are upserted on their source identity
`(company, KPI, period, estimate_type, as_of)`, so importing the same file twice
leaves the database unchanged. Add `--strict` to exit non-zero when any row was
rejected, or `--database-url` to target another database.

## Tests and checks

```bash
cd backend
ruff format --check . && ruff check . && mypy && pytest
```

```bash
cd web
npm run format:check && npm run lint && npm run test && npm run build
```

No test needs a network connection, an API key, or a live model provider.

Tests that need PostgreSQL create and use a separate `equity_metrics_test`
database, so they never touch development data. When no server is reachable they
skip with a message telling you how to start one, which keeps `pytest` runnable
anywhere. Point them elsewhere with `TEST_DATABASE_URL`.

## Architecture

```mermaid
flowchart LR
    U[Investor] --> W[React + TypeScript web app]
    W -->|POST /api/chat| A[FastAPI]
    A --> G[ai_gateway module]
    G --> L[LLM provider: mock or live]
    G --> M[MCP tools]
    C[External MCP client] -->|stdio| M
    A --> S[Shared KPI services]
    M --> S
    S --> P[(PostgreSQL)]
    M --> T[(mcp_tool_calls audit)]
```

A modular monolith. The pieces are separable, but they deploy as one unit.

| Package | Responsibility |
| --- | --- |
| `domain/` | Normalization, the recoverable-error vocabulary, response schemas. |
| `db/` | ORM models and the only module that builds SQL. |
| `services/` | Entity resolution, validation, retrieval. The shared core. |
| `api/` | Thin HTTP routes and error mapping. |
| `mcp_server/` | The four tools and the tool-call audit trail. |
| `ai_gateway/` | Provider isolation, the tool loop, its guardrails, the trace. |
| `importer/` | CSV validation and idempotent loading. |

The HTTP endpoints and the MCP tools both call `services/`, so validation and
retrieval exist once. The gateway reaches data only through the MCP tools, never
the database, which keeps one authoritative interface in front of PostgreSQL.

### Data model

```text
sectors(id, name, normalized_name)
companies(id, sector_id, name, normalized_name, ticker)
kpi_definitions(id, name, normalized_name, display_name, unit, description)
estimates(id, company_id, kpi_id, period, period_start, period_end,
          estimate_type, value, as_of)
mcp_tool_calls(id, correlation_id, tool_name, sanitized_arguments,
               outcome, error_code, duration_ms, created_at)
```

Values are `NUMERIC(20, 6)`, not floating point, so decimal precision is exact.
Check constraints enforce the estimate type, the period format, and the rule
that a QTD row must have an `as_of` date.

Three indexes carry the read paths: a unique index on the source identity, a
composite `(company_id, kpi_id, period)` for history, and a partial
`(company_id, kpi_id, as_of)` restricted to QTD rows for snapshots. The unique
index is declared `NULLS NOT DISTINCT`, because historical rows have a null
`as_of` and would otherwise be re-inserted on every import.

### Entity resolution

1. Normalize: trim, collapse whitespace, case-fold.
2. Exact uppercase ticker.
3. Exact normalized company or KPI name.
4. Otherwise, return a recoverable error carrying the normalized query and up to
   five suggestions.

A substring match is never promoted to a resolution, **even when only one
candidate exists**, because doing so would silently choose on the caller's
behalf. Substring matching is used for search, which is explicitly a list of
candidates. `%` and `_` in user input are escaped so they match literally.

## HTTP API

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health` | Liveness, used by the container health check. |
| `GET /api/sectors` | Sectors with company counts. |
| `GET /api/companies?query=&sector=&limit=` | Bounded company search. |
| `GET /api/kpis` | Every KPI in the dataset, with units. |
| `GET /api/companies/{company}/overview` | Every KPI for a company: full history **and** latest QTD, in one call. |
| `GET /api/companies/{company}/kpis` | Resolved company and the KPIs it reports. |
| `GET /api/companies/{company}/kpis/{kpi}/estimates?periods=` | Historical estimates, chronological. |
| `GET /api/companies/{company}/kpis/{kpi}/qtd` | Latest QTD snapshot, by greatest `as_of`. |
| `POST /api/chat` | An answer with its ordered tool trace. |

`{company}` accepts a ticker or an exact company name. Recoverable failures
return `code`, `message`, `normalized_query`, and `suggestions`, with `404` for
unknown entities, `409` for input resembling several known entities, and `400`
for a malformed period.

Estimate values are JSON strings so exact decimal precision survives the wire,
and every value travels with its unit.

## MCP server

| Tool | Purpose |
| --- | --- |
| `search_companies(query, sector?)` | Candidates with canonical name, ticker, and sector. |
| `list_company_kpis(ticker_or_company)` | Resolved company and its KPIs, with units. |
| `get_kpi_estimates(ticker, kpi, periods?)` | Historical estimates, chronological. |
| `get_qtd_estimate(ticker, kpi)` | Latest QTD snapshot, by greatest `as_of`. |

Run it over stdio:

```bash
cd backend
equity-mcp
```

### MCP client configuration

Use absolute paths. The database must be running and imported first.

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

On macOS or Linux the command is
`/path/to/equity-metrics-mcp/backend/.venv/bin/equity-mcp`.

### Errors and auditing

A recoverable failure is a tool *result* with `isError` set, never a protocol
error, so an agent can correct itself and retry. The payload carries a
machine-readable `code` — `unknown_company`, `ambiguous_company`, `unknown_kpi`,
`ambiguous_kpi`, `invalid_period`, `no_data` — the normalized query, and up to
five suggestions. Only malformed arguments, which no retry can fix from the
tool's side, remain protocol errors.

Every call writes one `mcp_tool_calls` row in a `finally` path, through its own
session so a rolled-back read cannot discard the audit and a storage failure
cannot mask a good answer. The row records the tool, sanitized and bounded
arguments, outcome, error code, duration, and a correlation ID shared by every
call made for one question. Credential- and prompt-bearing argument names are
redacted before storage.

```bash
docker compose exec db psql -U equity -d equity_metrics \
  -c "select correlation_id, tool_name, sanitized_arguments, outcome, error_code, duration_ms
      from mcp_tool_calls order by id desc limit 10;"
```

## AI gateway

`backend/src/equity_metrics/ai_gateway/` isolates every provider concern behind
one interface — `answer(question, context) -> AgentResponse`. It is a module,
not a service, but the contract is narrow enough that extracting it later would
not change its callers.

Guardrails on every answer:

| Guardrail | Setting | Default |
| --- | --- | --- |
| Tool iterations | `LLM_MAX_TOOL_ITERATIONS` | 6 |
| Per-provider-call timeout | `LLM_TIMEOUT_SECONDS` | 30 |
| Total answer budget | `LLM_TOTAL_TIMEOUT_SECONDS` | 90 |
| Retries, transient faults only | `LLM_MAX_RETRIES` | 2 |
| Tool response size | `MAX_TOOL_RESULT_CHARS` in code | 20,000 characters |

A permanent provider failure is never retried, because a rejected request fails
identically the second time.

### Providers

`mock` is the default and needs no credential. It plans a tool sequence from the
question, recovers from a recoverable tool error by retrying with the suggestion
the tool offered, and composes its answer only from returned payloads. The same
question always produces the same trace and the same words.

`anthropic` enables the live adapter. It needs `LLM_API_KEY` and
`pip install anthropic`, an optional dependency; without a key the gateway
refuses to build rather than falling back silently.

### Chat responses

`POST /api/chat` returns the answer, a request ID, the provider, model, and
prompt version, the ordered tool trace, and `data` — the structured payloads of
the successful tool calls. `data` exists so the UI can render figures as tables
instead of parsing them back out of prose; the sentence and the table come from
the same tool call and cannot disagree.

The request ID is the correlation ID on the `mcp_tool_calls` rows the answer
produced, so the visible trace and the audit trail line up.

## Chat UI

One screen, no navigation: header, suggested prompts, conversation, composer.
Each answer carries the prose reply, a data panel, and a collapsed activity
panel.

- Values are shown with their units, dates and figures in tabular numerals so
  columns line up, and quarter-to-date results carry a visible QTD badge that
  distinguishes them from history.
- The activity panel expands to every tool call in order with its sanitized
  arguments, outcome or error code, and duration, plus the request ID, model,
  and prompt version. A failure the loop recovered from stays visible there even
  though it is kept out of the answer.
- Enter submits, Shift+Enter adds a line. Loading, service failure, and network
  failure each have their own state, and wide tables scroll inside their card so
  the page never scrolls sideways.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Application shape | Modular monolith | Keeps the path from a change to a live answer short while preserving separable boundaries. |
| Shared core | One service layer behind both interfaces | The API and the MCP tools cannot drift apart on validation or retrieval. |
| Ambiguity | Refuse to resolve, return suggestions | Silently picking a company is the one failure an investor cannot see. |
| Tool errors | Results with `isError`, not protocol errors | An agent can read the code, correct the argument, and retry. |
| Numeric storage | `NUMERIC`, values as JSON strings | Financial figures must not be rounded by binary floating point in transit. |
| Latest QTD | Greatest `as_of`, never greatest value | "Latest" is a date, and in this dataset the two differ. |
| Provider isolation | `ai_gateway/` module | Keeps credentials, prompts, and the tool loop in one place without a second deployment to operate. |
| Default provider | Deterministic mock | The stack, and every test, runs with no credential and no network. |
| Gateway data access | Only through MCP tools | One authoritative interface in front of the database. |
| Audit writes | Separate session, `finally` path | A rolled-back read must not take the audit with it. |
| Import | Idempotent upsert on source identity | Re-running the import is a safe, boring operation. |
| Presentation | Tables, no charts | With 5 KPIs and 17 quarters, a table is faster to read than a chart. |

Two notes on the deviations from the original plan. The official MCP SDK renamed
`FastMCP` to `MCPServer` in `mcp` 2.x; this uses the current major version rather
than pinning to the previous one for a class name. And `POST /api/chat` returns
structured `data` alongside the prose, because a UI that has to parse figures
back out of a sentence cannot present them reliably.

## LLM tool-calling failure modes

The interesting engineering in an agent platform is not the happy path; it is
what the model does when it is wrong. Each row below is a failure mode this
system guards against, and where the guard lives.

| Failure mode | Guard |
| --- | --- |
| **Hallucinated entity** — the model asks for a ticker or KPI that does not exist | Resolution happens in SQL, never in the model. `TSLA` returns `unknown_company`; `EBITDA` returns `unknown_kpi` with the five real KPI names. |
| **Silent wrong match** — "Cloud" quietly resolves to one of three cloud companies | A substring match is never promoted to a resolution, even when unique. The tool returns `ambiguous_company` with candidates and refuses to choose. |
| **Unrecoverable error** — the model gets a stack trace it cannot act on | Business failures are tool *results* with `isError`, a machine-readable code, and up to five suggestions, so the model can correct the argument and retry. |
| **Infinite tool loop** — the model keeps calling tools and never answers | Fixed iteration ceiling (`LLM_MAX_TOOL_ITERATIONS`), then `tool_loop_exhausted`. |
| **Hanging provider** — a call never returns | Per-call timeout inside a total answer budget; both map to a `timeout` error. |
| **Retry storms** — a rejected request is retried until the budget is gone | Only *transient* faults retry, bounded and backed off. A 400 is never retried. |
| **Context blowup** — one oversized tool result fills the window | Tool results are truncated at a size bound and the truncation is flagged in the trace. |
| **Invented numbers in prose** — the model paraphrases a figure incorrectly | The UI renders the tool payloads directly as tables; the sentence and the table come from the same call and cannot disagree. |
| **Unit confusion** — a value is quoted without or with the wrong unit | The unit is carried on every value from the database through to the response, and the importer rejects a row whose unit contradicts its KPI. |
| **Precision loss** — a decimal is mangled in transit | `NUMERIC` storage, serialized as JSON strings, never binary floating point. |
| **Stale-vs-current confusion** — a QTD snapshot is read as a closed quarter | Historical and QTD are separate tools and separate response shapes; QTD always carries `as_of`, and the UI badges it. |
| **Unauditable behavior** — nobody can reconstruct what the agent did | Every call writes an audit row in a `finally` path with a correlation ID shared by the whole question. |
| **Secrets in logs** — a prompt or key ends up in the audit table | Argument names matching credential or prompt patterns are redacted, and values are length-bounded, before storage. |
| **Scope drift** — the model answers a narrower question than the one asked | A multi-company question is declined rather than answered for one company; a named fiscal period is passed to the tool rather than ignored. |

## Future improvements

Deliberately excluded from this build, with the path each would take:

- **Authentication and entitlements.** Add an identity provider in front of the
  API, carry the subject through the gateway into the audit rows, and filter
  retrieval by entitlement in the service layer, which is already the single
  place that queries.
- **Multi-tenancy.** A tenant column on the reference tables plus a session-level
  filter, or schema-per-tenant if isolation must be physical.
- **Provider policy.** The gateway is the natural home for per-tenant model
  choice, spend caps, and content policy; it already owns the request path and
  records usage.
- **Synonym management.** A curated alias table consulted between exact match and
  suggestions, so "Acme" resolves without weakening the no-guessing rule.
- **Caching.** Reference data changes rarely; a short-lived cache of resolution
  lookups would cut most repeated queries. It was left out because correctness,
  not latency, is the constraint at this size.
- **Pagination.** Response bounds are in place, but a larger dataset needs cursor
  pagination on search and history.
- **Charts.** Worth adding when a question is genuinely better answered by a
  shape than a column of numbers, not before.
- **CI/CD, rate limits, production monitoring.** The checks in this README are
  the pipeline definition; structured JSON logs are ready for a collector, and
  the audit table is ready to be a metrics source.
- **A separately deployed gateway.** The interface is already narrow enough that
  this becomes a transport change rather than a rewrite.

## Use of AI tools

Implementation of this repository was AI-assisted throughout, using Claude Code
(Claude Opus 5), built in reviewed stages rather than in one pass.

### Where AI output was relied on

Mechanical and repetitive work: model and schema definitions, the migration
body, CSS and component scaffolding, Dockerfiles and tool configuration, and
test bodies once the cases to cover had been chosen. AI was also effective at
enumerating edge cases around an already-specified behavior.

Where recall was not trusted: the MCP Python SDK changed shape in 2.x, so the
actual `MCPServer` API was probed in a scratch script before any code was
written against it, rather than assuming the older `FastMCP` interface.

### Where deliberate design was required

These were settled before the code was written, and are the points where
accepting a plausible-looking default would have produced a worse system. Each
is documented with its reasoning in [Decisions](#decisions) and
[LLM tool-calling failure modes](#llm-tool-calling-failure-modes):

- **Tool granularity** — four task-shaped tools rather than one generic `query`
  tool, each with small explicit arguments.
- **Refusing to resolve ambiguity** — a substring match is never promoted to a
  resolution, even when unique, because a silently wrong company is the failure
  an investor cannot detect.
- **The error contract** — recoverable failures as tool results with a
  machine-readable code and bounded suggestions, not protocol errors.
- **The audit path** — written in a `finally` block through its own session, so
  a rolled-back read cannot discard the audit and an audit failure cannot
  corrupt a good answer.
- **Security boundary between model and data** — the gateway invokes tools but
  never queries the database; all SQL is in one module and parameterized; `LIKE`
  wildcards are escaped; audit arguments are redacted and bounded.
- **Loop guardrails** — iteration ceiling, per-call timeout inside a total
  budget, response-size bound, retries restricted to transient faults.
- **Schema and index design** — `NUMERIC` rather than float, and the
  `NULLS NOT DISTINCT` unique index without which every re-import would
  duplicate all 1,600 historical rows.
- **"Latest QTD" semantics** — greatest `as_of`, never greatest value. The two
  differ in this dataset, so a plausible `MAX(value)` implementation would
  return a wrong number that still looks right.

### Verification

AI output was checked against a running system rather than only a passing test
suite: the stack was rebuilt from an empty volume, the MCP server was driven
over stdio by a real client, and questions were replayed through the live API
while reading the audit table. Two defects surfaced that way, both invisible to
the tests that existed at the time — a named fiscal period was ignored so the
wrong quarter was returned, and a two-company comparison was answered for one
company. Both are fixed and covered by tests.

The dataset and the product requirements were provided, not generated. No KPI
value in this repository was produced by a model.
