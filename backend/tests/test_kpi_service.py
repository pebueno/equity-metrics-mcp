"""Entity resolution and retrieval behavior of the shared KPI services."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from equity_metrics.domain.errors import (
    AmbiguousCompanyError,
    AmbiguousKpiError,
    InvalidPeriodError,
    NoDataError,
    UnknownCompanyError,
    UnknownKpiError,
)
from equity_metrics.services import kpi_service


class TestCompanyResolution:
    def test_resolves_an_exact_ticker(self, seeded_session: Session) -> None:
        assert kpi_service.resolve_company(seeded_session, "ACME").ticker == "ACME"

    def test_resolves_a_ticker_regardless_of_case_and_padding(
        self, seeded_session: Session
    ) -> None:
        assert kpi_service.resolve_company(seeded_session, "  acme ").ticker == "ACME"

    def test_resolves_an_exact_company_name(self, seeded_session: Session) -> None:
        company = kpi_service.resolve_company(seeded_session, "acme   E-COMMERCE")

        assert company.ticker == "ACME"

    def test_reports_unknown_company_without_suggestions(self, seeded_session: Session) -> None:
        with pytest.raises(UnknownCompanyError) as exc:
            kpi_service.resolve_company(seeded_session, "Nonexistent Holdings")

        assert exc.value.code == "unknown_company"
        assert exc.value.normalized_query == "Nonexistent Holdings"
        assert exc.value.suggestions == []

    def test_refuses_to_guess_between_near_matches(self, seeded_session: Session) -> None:
        with pytest.raises(AmbiguousCompanyError) as exc:
            kpi_service.resolve_company(seeded_session, "Cloud")

        assert exc.value.code == "ambiguous_company"
        assert {s.value for s in exc.value.suggestions} == {"CLD9", "STRT"}

    def test_refuses_to_guess_even_for_a_single_near_match(self, seeded_session: Session) -> None:
        with pytest.raises(AmbiguousCompanyError) as exc:
            kpi_service.resolve_company(seeded_session, "ShieldNet")

        assert [s.value for s in exc.value.suggestions] == ["SHLD"]

    def test_bounds_suggestions(self, seeded_session: Session) -> None:
        with pytest.raises(AmbiguousCompanyError) as exc:
            kpi_service.resolve_company(seeded_session, "e")

        assert len(exc.value.suggestions) == 5


class TestKpiResolution:
    def test_resolves_an_exact_kpi_name(self, seeded_session: Session) -> None:
        assert kpi_service.resolve_kpi(seeded_session, "ASP ($)").name == "ASP ($)"

    def test_normalizes_case_and_whitespace(self, seeded_session: Session) -> None:
        assert kpi_service.resolve_kpi(seeded_session, "  total   REVENUE ($MM) ").unit == "$MM"

    def test_suggests_kpis_for_a_partial_name(self, seeded_session: Session) -> None:
        with pytest.raises(AmbiguousKpiError) as exc:
            kpi_service.resolve_kpi(seeded_session, "subscribers")

        assert {s.value for s in exc.value.suggestions} == {
            "Global Net Added Subscribers",
            "U.S. Net Added Subscribers",
        }

    def test_lists_available_kpis_when_nothing_matches(self, seeded_session: Session) -> None:
        with pytest.raises(UnknownKpiError) as exc:
            kpi_service.resolve_kpi(seeded_session, "EBITDA")

        assert exc.value.code == "unknown_kpi"
        assert len(exc.value.suggestions) == 5


class TestSearch:
    def test_matches_name_and_ticker(self, seeded_session: Session) -> None:
        result = kpi_service.search_companies(seeded_session, query="acme")

        assert [company.ticker for company in result.companies] == ["ACME"]

    def test_filters_by_sector(self, seeded_session: Session) -> None:
        result = kpi_service.search_companies(seeded_session, query="", sector="Cloud")

        assert [company.ticker for company in result.companies] == ["CLD9", "NIMB", "STRT"]

    def test_is_bounded_and_ordered_by_name(self, seeded_session: Session) -> None:
        result = kpi_service.search_companies(seeded_session, query="", limit=3)

        names = [company.company_name for company in result.companies]
        assert names == sorted(names)
        assert len(names) == 3

    def test_treats_wildcards_as_literal_text(self, seeded_session: Session) -> None:
        assert kpi_service.search_companies(seeded_session, query="%").companies == []

    def test_lists_sectors_with_company_counts(self, seeded_session: Session) -> None:
        sectors = kpi_service.list_sectors(seeded_session)

        assert len(sectors) == 18
        assert next(s.company_count for s in sectors if s.sector == "Cloud") == 3


class TestCompanyKpis:
    def test_lists_the_kpis_a_company_reports(self, seeded_session: Session) -> None:
        result = kpi_service.list_company_kpis(seeded_session, "acme")

        assert result.company.ticker == "ACME"
        assert result.company.sector == "E-commerce"
        assert [kpi.kpi for kpi in result.kpis] == [
            "ASP ($)",
            "Global Net Added Subscribers",
            "Total Revenue ($MM)",
            "U.S. Net Added Subscribers",
            "Units Sold",
        ]
        assert next(kpi.unit for kpi in result.kpis if kpi.kpi == "ASP ($)") == "$"


class TestHistoricalEstimates:
    def test_returns_every_period_in_chronological_order(self, seeded_session: Session) -> None:
        result = kpi_service.get_historical_estimates(
            seeded_session, company_query="ACME", kpi_query="ASP ($)"
        )

        periods = [point.period for point in result.estimates]
        assert periods == sorted(periods)
        assert periods[0] == "2022Q1"
        assert periods[-1] == "2025Q4"
        assert result.unit == "$"

    def test_filters_to_the_requested_periods(self, seeded_session: Session) -> None:
        result = kpi_service.get_historical_estimates(
            seeded_session,
            company_query="ACME",
            kpi_query="ASP ($)",
            periods=["2022q2", " 2022Q1 "],
        )

        assert [point.period for point in result.estimates] == ["2022Q1", "2022Q2"]

    def test_rejects_a_malformed_period(self, seeded_session: Session) -> None:
        with pytest.raises(InvalidPeriodError) as exc:
            kpi_service.get_historical_estimates(
                seeded_session, company_query="ACME", kpi_query="ASP ($)", periods=["2022Q5"]
            )

        assert exc.value.code == "invalid_period"

    def test_reports_no_data_for_a_period_without_estimates(self, seeded_session: Session) -> None:
        with pytest.raises(NoDataError):
            kpi_service.get_historical_estimates(
                seeded_session, company_query="ACME", kpi_query="ASP ($)", periods=["2019Q1"]
            )


class TestQtdEstimate:
    def test_returns_the_snapshot_with_the_greatest_as_of_date(
        self, seeded_session: Session
    ) -> None:
        result = kpi_service.get_latest_qtd_estimate(
            seeded_session, company_query="ACME", kpi_query="ASP ($)"
        )

        # 2026-02-15 carries the larger value (169.64); latest means latest date.
        assert result.as_of == dt.date(2026, 3, 15)
        assert result.value == Decimal("164.220000")
        assert result.period == "2026Q1"
        assert result.unit == "$"
