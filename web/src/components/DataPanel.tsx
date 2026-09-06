import type { ReactElement } from 'react';

import type {
  CompanyKpis,
  CompanySearchResult,
  HistoricalEstimates,
  QtdEstimate,
  ToolPayloadItem,
} from '../types';
import {
  asCompanyKpis,
  asCompanySearchResult,
  asHistoricalEstimates,
  asQtdEstimate,
} from './guards';

/**
 * Renders the tool payloads behind an answer as tables.
 *
 * The prose and these numbers come from the same tool call, so the reader can
 * check the sentence against the data without a second request.
 */
export default function DataPanel({ items }: { items: ToolPayloadItem[] }) {
  const rendered = items.map(renderItem).filter((node) => node !== null);
  if (rendered.length === 0) {
    return null;
  }
  return <div className="data-panel">{rendered}</div>;
}

function renderItem(item: ToolPayloadItem, index: number): ReactElement | null {
  const key = `${item.tool}-${index}`;
  switch (item.tool) {
    case 'get_qtd_estimate': {
      const value = asQtdEstimate(item.data);
      return value && <QtdCard key={key} value={value} />;
    }
    case 'get_kpi_estimates': {
      const value = asHistoricalEstimates(item.data);
      return value && <HistoryTable key={key} value={value} />;
    }
    case 'list_company_kpis': {
      const value = asCompanyKpis(item.data);
      return value && <KpiTable key={key} value={value} />;
    }
    case 'search_companies': {
      const value = asCompanySearchResult(item.data);
      return value && <CompanyTable key={key} value={value} />;
    }
    default:
      return null;
  }
}

function QtdCard({ value }: { value: QtdEstimate }) {
  return (
    <section className="data-card" aria-label={`${value.kpi} quarter to date`}>
      <header className="data-card__head">
        <div>
          <span className="ticker">{value.company.ticker}</span>
          <span className="company">{value.company.company_name}</span>
        </div>
        <span className="badge badge--qtd">QTD</span>
      </header>
      <p className="figure">
        <span className="figure__value">{value.value}</span>
        <span className="figure__unit">{value.unit}</span>
      </p>
      <dl className="meta">
        <div>
          <dt>KPI</dt>
          <dd>{value.kpi}</dd>
        </div>
        <div>
          <dt>Fiscal period</dt>
          <dd>{value.period}</dd>
        </div>
        <div>
          <dt>As of</dt>
          <dd className="numeric">{value.as_of}</dd>
        </div>
      </dl>
    </section>
  );
}

function HistoryTable({ value }: { value: HistoricalEstimates }) {
  return (
    <section className="data-card" aria-label={`${value.kpi} history`}>
      <header className="data-card__head">
        <div>
          <span className="ticker">{value.company.ticker}</span>
          <span className="company">{value.company.company_name}</span>
        </div>
        <span className="badge">Historical</span>
      </header>
      <p className="data-card__subject">
        {value.kpi} <span className="muted">({value.unit})</span>
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <caption className="visually-hidden">
            {value.kpi} by fiscal period, in {value.unit}
          </caption>
          <thead>
            <tr>
              <th scope="col">Period</th>
              <th scope="col">Ends</th>
              <th scope="col" className="align-right">
                Value
              </th>
              <th scope="col">Unit</th>
            </tr>
          </thead>
          <tbody>
            {value.estimates.map((point) => (
              <tr key={point.period}>
                <th scope="row" className="numeric">
                  {point.period}
                </th>
                <td className="numeric muted">{point.period_end}</td>
                <td className="numeric align-right strong">{point.value}</td>
                <td className="muted">{point.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function KpiTable({ value }: { value: CompanyKpis }) {
  return (
    <section className="data-card" aria-label="Available KPIs">
      <header className="data-card__head">
        <div>
          <span className="ticker">{value.company.ticker}</span>
          <span className="company">{value.company.company_name}</span>
        </div>
        <span className="badge">{value.company.sector}</span>
      </header>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">KPI</th>
              <th scope="col">Unit</th>
            </tr>
          </thead>
          <tbody>
            {value.kpis.map((kpi) => (
              <tr key={kpi.kpi}>
                <th scope="row">{kpi.kpi}</th>
                <td className="muted">{kpi.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CompanyTable({ value }: { value: CompanySearchResult }) {
  // A single match is already reflected in the answer and the follow-up call.
  if (value.companies.length < 2) {
    return null;
  }
  return (
    <section className="data-card" aria-label="Matching companies">
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Company</th>
              <th scope="col">Sector</th>
            </tr>
          </thead>
          <tbody>
            {value.companies.map((company) => (
              <tr key={company.ticker}>
                <th scope="row" className="numeric">
                  {company.ticker}
                </th>
                <td>{company.company_name}</td>
                <td className="muted">{company.sector}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
