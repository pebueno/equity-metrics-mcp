import type {
  CompanyKpis,
  CompanySearchResult,
  CompanySummary,
  EstimatePoint,
  HistoricalEstimates,
  QtdEstimate,
} from '../types';

/**
 * Shape checks for tool payloads.
 *
 * The payloads arrive as `Record<string, unknown>`, so asserting a type on them
 * would let a changed or truncated payload reach the DOM and throw while
 * rendering. Narrowing here instead means an unrecognised shape is simply not
 * drawn, and the prose answer still stands.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isCompany(value: unknown): value is CompanySummary {
  return (
    isRecord(value) &&
    isString(value.ticker) &&
    isString(value.company_name) &&
    isString(value.sector)
  );
}

function isEstimatePoint(value: unknown): value is EstimatePoint {
  return (
    isRecord(value) &&
    isString(value.period) &&
    isString(value.period_start) &&
    isString(value.period_end) &&
    isString(value.value) &&
    isString(value.unit)
  );
}

export function asQtdEstimate(value: unknown): QtdEstimate | null {
  if (
    isRecord(value) &&
    isCompany(value.company) &&
    isString(value.kpi) &&
    isString(value.period) &&
    isString(value.value) &&
    isString(value.unit) &&
    isString(value.as_of)
  ) {
    return value as unknown as QtdEstimate;
  }
  return null;
}

export function asHistoricalEstimates(value: unknown): HistoricalEstimates | null {
  if (
    isRecord(value) &&
    isCompany(value.company) &&
    isString(value.kpi) &&
    isString(value.unit) &&
    Array.isArray(value.estimates) &&
    value.estimates.every(isEstimatePoint)
  ) {
    return value as unknown as HistoricalEstimates;
  }
  return null;
}

export function asCompanyKpis(value: unknown): CompanyKpis | null {
  if (
    isRecord(value) &&
    isCompany(value.company) &&
    Array.isArray(value.kpis) &&
    value.kpis.every((kpi) => isRecord(kpi) && isString(kpi.kpi) && isString(kpi.unit))
  ) {
    return value as unknown as CompanyKpis;
  }
  return null;
}

export function asCompanySearchResult(value: unknown): CompanySearchResult | null {
  if (
    isRecord(value) &&
    isString(value.query) &&
    Array.isArray(value.companies) &&
    value.companies.every(isCompany)
  ) {
    return value as unknown as CompanySearchResult;
  }
  return null;
}
