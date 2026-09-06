"""Deterministic provider used for local runs and every test.

It plans a tool sequence from keywords, recovers from a recoverable tool error
by retrying with the first suggestion, and writes its answer only from what the
tools returned. Given the same question it always produces the same trace and
the same words, so no test needs a network, a key, or a live model.
"""

import json
import re
from typing import Any

from equity_metrics.ai_gateway.contracts import (
    AssistantTurn,
    ProviderCompletion,
    ToolCallRequest,
    ToolCallResult,
    ToolResultTurn,
    ToolSpec,
    Turn,
    Usage,
    UserTurn,
)

# Uppercase words that look like tickers but are units or jargon in this domain.
NON_TICKER_WORDS = frozenset({"QTD", "KPI", "ASP", "US", "USA", "MM", "Q1", "Q2", "Q3", "Q4"})
TICKER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]{2,5}\b")

KPI_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("total revenue", "Total Revenue ($MM)"),
    ("revenue", "Total Revenue ($MM)"),
    ("asp", "ASP ($)"),
    ("average selling price", "ASP ($)"),
    ("units sold", "Units Sold"),
    ("units", "Units Sold"),
    ("global net added subscribers", "Global Net Added Subscribers"),
    ("global subscriber", "Global Net Added Subscribers"),
    ("u.s. net added subscribers", "U.S. Net Added Subscribers"),
    ("u.s. subscriber", "U.S. Net Added Subscribers"),
    ("us subscriber", "U.S. Net Added Subscribers"),
    ("domestic subscriber", "U.S. Net Added Subscribers"),
    # Longest match wins, so the qualified forms above are tried first and this
    # bare prefix catches "subscriber", "subscribers", and "subscriber growth".
    ("subscriber", "Global Net Added Subscribers"),
)

QTD_KEYWORDS = (
    "qtd",
    "quarter-to-date",
    "quarter to date",
    "current quarter",
    "this quarter",
    "so far this",
    "right now",
    "currently",
    "to date",
)

# An explicit fiscal period in the question, e.g. "revenue in 2023Q2".
PERIOD_PATTERN = re.compile(r"\b(\d{4})\s*[qQ]([1-4])\b")

# Asking about several companies at once, which no single tool can answer.
COMPARISON_WORDS = ("compare", "versus", " vs ", " vs. ", "difference between")

# Beyond a handful of named periods it is simpler to return the full history.
MAX_REQUESTED_PERIODS = 8

# Words that carry no company signal, dropped before searching.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "give",
        "had",
        "has",
        "have",
        "how",
        "in",
        "is",
        "it",
        "its",
        "latest",
        "me",
        "most",
        "much",
        "of",
        "on",
        "or",
        "please",
        "recent",
        "show",
        "tell",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "what",
        "whats",
        "when",
        "where",
        "which",
        "who",
        "with",
        "your",
    ]
)
WORD_PATTERN = re.compile(r"[a-z0-9.&'-]+")

MAX_PERIODS_IN_ANSWER = 4


class MockProvider:
    """A scripted provider whose answers are grounded in tool output."""

    def __init__(self, model: str = "mock-model") -> None:
        self._model = model

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return self._model

    async def complete(
        self, system: str, turns: tuple[Turn, ...], tools: tuple[ToolSpec, ...]
    ) -> ProviderCompletion:
        """Return the next tool calls, or the final answer once data is in hand."""
        question = _question(turns)
        last_results = _last_results(turns)

        if last_results is None:
            unsupported = _unsupported(question)
            if unsupported is not None:
                # Answering for one company would look like an answer to a
                # question about two. Say what is possible instead.
                return _completion(text=unsupported)
            return _completion(tool_calls=_plan(question))

        recovery = _recover(last_results)
        if recovery is not None and not _already_attempted(turns, recovery):
            return _completion(tool_calls=(recovery,))

        follow_up = _after_search(question, last_results)
        if follow_up is not None and not _already_attempted(turns, follow_up):
            return _completion(tool_calls=(follow_up,))

        return _completion(text=_answer(question, turns))


def _completion(
    *, text: str | None = None, tool_calls: tuple[ToolCallRequest, ...] = ()
) -> ProviderCompletion:
    """Wrap a decision with deterministic, length-derived token counts."""
    body = text or json.dumps([call.arguments for call in tool_calls], sort_keys=True)
    return ProviderCompletion(
        text=text,
        tool_calls=tool_calls,
        usage=Usage(input_tokens=len(body) // 4, output_tokens=max(1, len(body) // 8)),
    )


def _question(turns: tuple[Turn, ...]) -> str:
    return next((turn.text for turn in turns if isinstance(turn, UserTurn)), "")


def _last_results(turns: tuple[Turn, ...]) -> tuple[ToolCallResult, ...] | None:
    if turns and isinstance(turns[-1], ToolResultTurn):
        return turns[-1].results
    return None


def _plan(question: str) -> tuple[ToolCallRequest, ...]:
    """Choose the opening tool call from the shape of the question."""
    ticker = _ticker(question)
    kpi = _kpi(question)

    if ticker is None:
        return (
            ToolCallRequest(
                id="call-1", name="search_companies", arguments={"query": _search_query(question)}
            ),
        )
    if kpi is None:
        return (
            ToolCallRequest(
                id="call-1", name="list_company_kpis", arguments={"ticker_or_company": ticker}
            ),
        )
    return (_estimate_call("call-1", question, ticker, kpi),)


def _estimate_call(call_id: str, question: str, ticker: str, kpi: str) -> ToolCallRequest:
    """Pick the QTD tool or the history tool, honouring any period the question names."""
    periods = _periods(question)
    lowered = question.lower()

    # A named fiscal period is a request for history, even alongside QTD wording:
    # "2023Q2" is a closed quarter, so a quarter-to-date snapshot cannot answer it.
    if not periods and any(keyword in lowered for keyword in QTD_KEYWORDS):
        return ToolCallRequest(
            id=call_id, name="get_qtd_estimate", arguments={"ticker": ticker, "kpi": kpi}
        )

    arguments: dict[str, Any] = {"ticker": ticker, "kpi": kpi}
    if periods:
        arguments["periods"] = periods
    return ToolCallRequest(id=call_id, name="get_kpi_estimates", arguments=arguments)


def _periods(question: str) -> list[str]:
    """Extract the fiscal periods a question names, in the order they appear."""
    found: list[str] = []
    for year, quarter in PERIOD_PATTERN.findall(question):
        period = f"{year}Q{quarter}"
        if period not in found:
            found.append(period)
    return found[:MAX_REQUESTED_PERIODS]


def _recover(results: tuple[ToolCallResult, ...]) -> ToolCallRequest | None:
    """Retry a failed call using the first suggestion the tool offered."""
    for result in results:
        if not result.is_error:
            continue
        payload = _loads(result.payload)
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            continue
        suggestions = error.get("suggestions") or []
        # Only a single suggestion is unambiguous enough to retry unattended.
        if len(suggestions) != 1:
            continue
        value = suggestions[0].get("value")
        if not isinstance(value, str):
            continue
        argument = (
            "kpi" if error.get("code", "").endswith("kpi") else _company_argument(result.name)
        )
        # Keep every other argument the call already had, so only the field the
        # tool objected to changes.
        return ToolCallRequest(
            id=f"{result.id}-retry",
            name=result.name,
            arguments={**result.arguments, argument: value},
        )
    return None


def _after_search(question: str, results: tuple[ToolCallResult, ...]) -> ToolCallRequest | None:
    """Once a search resolves to exactly one company, go get its numbers."""
    for result in results:
        if result.name != "search_companies" or result.is_error:
            continue
        payload = _loads(result.payload)
        companies = payload.get("companies") if isinstance(payload, dict) else None
        if not isinstance(companies, list) or len(companies) != 1:
            continue
        ticker = companies[0].get("ticker")
        if not isinstance(ticker, str):
            continue
        kpi = _kpi(question)
        if kpi is None:
            return ToolCallRequest(
                id="call-2", name="list_company_kpis", arguments={"ticker_or_company": ticker}
            )
        return _estimate_call("call-2", question, ticker, kpi)
    return None


def _already_attempted(turns: tuple[Turn, ...], candidate: ToolCallRequest) -> bool:
    """Avoid repeating a call that has already been made with the same arguments."""
    for turn in turns:
        if isinstance(turn, AssistantTurn):
            for call in turn.tool_calls:
                if call.name == candidate.name and call.arguments == candidate.arguments:
                    return True
    return False


def _answer(question: str, turns: tuple[Turn, ...]) -> str:
    """Compose the reply strictly from the payloads the tools returned."""
    results = [
        result for turn in turns if isinstance(turn, ToolResultTurn) for result in turn.results
    ]
    # A failure the loop went on to recover from is loop mechanics, not something
    # the investor needs in the answer; the tool trace still shows it.
    recovered = {result.name for result in results if not result.is_error}
    sections = [
        rendered
        for result in results
        if not (result.is_error and result.name in recovered)
        for rendered in (_render(result),)
        if rendered
    ]
    if not sections:
        return "I could not retrieve any data for that question."
    return "\n".join(sections)


def _render(result: ToolCallResult) -> str:
    """Render one tool payload as a sentence, inventing nothing."""
    payload = _loads(result.payload)
    if not isinstance(payload, dict):
        return ""
    if result.is_error:
        return _render_error(payload)
    if result.name == "get_qtd_estimate":
        return _render_qtd(payload)
    if result.name == "get_kpi_estimates":
        return _render_history(payload)
    if result.name == "list_company_kpis":
        return _render_kpis(payload)
    if result.name == "search_companies":
        return _render_search(payload)
    return ""


def _render_error(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if not isinstance(error, dict):
        return "The request could not be completed."
    message = error.get("message", "The request could not be completed.")
    suggestions = [s.get("label") for s in error.get("suggestions") or [] if isinstance(s, dict)]
    if suggestions:
        return f"{message} Candidates: {', '.join(str(s) for s in suggestions)}."
    return str(message)


def _render_qtd(payload: dict[str, Any]) -> str:
    company = payload.get("company", {})
    return (
        f"{company.get('company_name')} ({company.get('ticker')}) "
        f"{payload.get('kpi')} quarter-to-date for {payload.get('period')} is "
        f"{payload.get('value')} {payload.get('unit')}, as of {payload.get('as_of')}."
    )


def _render_history(payload: dict[str, Any]) -> str:
    company = payload.get("company", {})
    estimates = payload.get("estimates") or []
    recent = estimates[-MAX_PERIODS_IN_ANSWER:]
    points = ", ".join(
        f"{point.get('period')}: {point.get('value')} {point.get('unit')}" for point in recent
    )
    return (
        f"{company.get('company_name')} ({company.get('ticker')}) historical "
        f"{payload.get('kpi')} — {points}."
    )


def _render_kpis(payload: dict[str, Any]) -> str:
    company = payload.get("company", {})
    names = ", ".join(f"{kpi.get('kpi')} ({kpi.get('unit')})" for kpi in payload.get("kpis") or [])
    return f"{company.get('company_name')} ({company.get('ticker')}) reports: {names}."


def _render_search(payload: dict[str, Any]) -> str:
    companies = payload.get("companies") or []
    if not companies:
        return f"No company matched {payload.get('query')!r}."
    if len(companies) == 1:
        return ""
    listed = ", ".join(f"{c.get('company_name')} ({c.get('ticker')})" for c in companies)
    return f"Several companies match: {listed}. Which one did you mean?"


def _search_query(question: str) -> str:
    """Reduce a question to the words that might name a company.

    Feeding a whole sentence to a substring search matches nothing, so the KPI
    and quarter-to-date phrasing is removed along with ordinary filler words.
    """
    lowered = question.lower()
    for phrase in QTD_KEYWORDS:
        lowered = lowered.replace(phrase, " ")
    for keyword, _ in KPI_KEYWORDS:
        lowered = lowered.replace(keyword, " ")
    words = [word for word in WORD_PATTERN.findall(lowered) if word not in STOPWORDS]
    return " ".join(words) or question


def _unsupported(question: str) -> str | None:
    """Return a refusal when the question asks for something no tool can answer.

    Only comparisons are detected, because they are the case where a partial
    answer reads as a complete one.
    """
    lowered = f" {question.lower()} "
    asks_to_compare = any(word in lowered for word in COMPARISON_WORDS)
    if asks_to_compare or len(_tickers(question)) > 1:
        return (
            "I can only report one company at a time. Ask about each company "
            "separately, for example by naming a single ticker per question."
        )
    return None


def _tickers(question: str) -> list[str]:
    """Every ticker-shaped word in the question, in order."""
    return [
        match.group()
        for match in TICKER_PATTERN.finditer(question)
        if match.group() not in NON_TICKER_WORDS
    ]


def _ticker(question: str) -> str | None:
    """The first ticker-shaped word in the question, if any."""
    found = _tickers(question)
    return found[0] if found else None


def _kpi(question: str) -> str | None:
    lowered = question.lower()
    for keyword, name in KPI_KEYWORDS:
        if keyword in lowered:
            return name
    return None


def _company_argument(tool_name: str) -> str:
    return "ticker_or_company" if tool_name == "list_company_kpis" else "ticker"


def _loads(payload: str) -> Any:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
