"""Row-level validation rules; no database required."""

import datetime as dt
from decimal import Decimal

import pytest

from equity_metrics.importer.rows import RowValidationError, parse_row

VALID_ROW = {
    "company_name": "Acme E-commerce",
    "ticker": "acme",
    "sector": "E-commerce",
    "kpi": "ASP ($)",
    "period_start": "2022-01-01",
    "period_end": "2022-03-31",
    "period": "2022Q1",
    "estimate_type": "historical",
    "value": "128.67",
    "unit": "$",
    "as_of": "",
}


def test_parses_and_normalizes_a_valid_row() -> None:
    row = parse_row({**VALID_ROW, "company_name": "  Acme   E-commerce ", "kpi": "ASP  ($)"})

    assert row.ticker == "ACME"
    assert row.company_name == "Acme E-commerce"
    assert row.kpi == "ASP ($)"
    assert row.value == Decimal("128.67")
    assert row.period_start == dt.date(2022, 1, 1)
    assert row.as_of is None


def test_preserves_decimal_precision() -> None:
    assert parse_row({**VALID_ROW, "value": "128.670"}).value == Decimal("128.670")


@pytest.mark.parametrize("period", ["2022Q5", "22Q1", "2022-Q1", "2022", ""])
def test_rejects_malformed_periods(period: str) -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "period": period})

    assert exc.value.field == "period"


def test_rejects_unknown_estimate_type() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "estimate_type": "forecast"})

    assert exc.value.field == "estimate_type"


def test_rejects_non_numeric_value() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "value": "n/a"})

    assert exc.value.field == "value"


def test_requires_as_of_for_qtd_rows() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "estimate_type": "qtd", "as_of": ""})

    assert exc.value.field == "as_of"


def test_accepts_qtd_rows_with_a_snapshot_date() -> None:
    row = parse_row({**VALID_ROW, "estimate_type": "qtd", "as_of": "2022-02-15"})

    assert row.estimate_type == "qtd"
    assert row.as_of == dt.date(2022, 2, 15)


def test_rejects_missing_required_field() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "ticker": "  "})

    assert exc.value.field == "ticker"


def test_rejects_period_end_before_period_start() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "period_end": "2021-12-31"})

    assert exc.value.field == "period_end"


def test_rejects_malformed_date() -> None:
    with pytest.raises(RowValidationError) as exc:
        parse_row({**VALID_ROW, "period_start": "01/01/2022"})

    assert exc.value.field == "period_start"
