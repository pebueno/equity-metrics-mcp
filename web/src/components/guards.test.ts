import { describe, expect, test } from 'vitest';

import { asCompanySearchResult, asHistoricalEstimates, asQtdEstimate } from './guards';

const COMPANY = { ticker: 'ACME', company_name: 'Acme E-commerce', sector: 'E-commerce' };

describe('payload guards', () => {
  test('accepts a well-formed QTD payload', () => {
    const value = asQtdEstimate({
      company: COMPANY,
      kpi: 'ASP ($)',
      period: '2026Q1',
      period_start: '2026-01-01',
      period_end: '2026-03-31',
      value: '164.22',
      unit: '$',
      as_of: '2026-03-15',
    });

    expect(value?.value).toBe('164.22');
  });

  test('rejects a payload missing the snapshot date', () => {
    expect(
      asQtdEstimate({ company: COMPANY, kpi: 'ASP ($)', period: '2026Q1', value: '164.22' }),
    ).toBeNull();
  });

  test('rejects a numeric value where a decimal string is expected', () => {
    // The API sends decimals as strings to preserve precision; a bare number
    // means the contract changed and the payload should not be rendered.
    expect(
      asQtdEstimate({
        company: COMPANY,
        kpi: 'ASP ($)',
        period: '2026Q1',
        period_start: '2026-01-01',
        period_end: '2026-03-31',
        value: 164.22,
        unit: '$',
        as_of: '2026-03-15',
      }),
    ).toBeNull();
  });

  test('rejects history whose rows are malformed', () => {
    expect(
      asHistoricalEstimates({
        company: COMPANY,
        kpi: 'ASP ($)',
        unit: '$',
        estimates: [{ period: '2022Q1' }],
      }),
    ).toBeNull();
  });

  test('accepts an empty search result', () => {
    expect(asCompanySearchResult({ query: 'nothing', companies: [] })?.companies).toEqual([]);
  });

  test.each([null, undefined, 'a string', 42, []])('rejects %o', (value) => {
    expect(asQtdEstimate(value)).toBeNull();
  });
});
