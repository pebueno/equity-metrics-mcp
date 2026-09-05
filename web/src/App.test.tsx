import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, test, vi } from 'vitest';

import App from './App';
import type { ChatResponse } from './types';

const QTD_RESPONSE: ChatResponse = {
  answer:
    'Acme E-commerce (ACME) ASP ($) quarter-to-date for 2026Q1 is 164.22 $, as of 2026-03-15.',
  request_id: 'req-1',
  provider: 'mock',
  model: 'mock-model',
  prompt_version: 'v1',
  iterations: 2,
  duration_ms: 42,
  created_at: '2026-03-15T00:00:00Z',
  trace: [
    {
      index: 1,
      tool: 'get_qtd_estimate',
      arguments: { ticker: 'ACME', kpi: 'ASP ($)' },
      status: 'ok',
      duration_ms: 9,
      error_code: null,
      truncated: false,
    },
  ],
  data: [
    {
      tool: 'get_qtd_estimate',
      data: {
        company: { ticker: 'ACME', company_name: 'Acme E-commerce', sector: 'E-commerce' },
        kpi: 'ASP ($)',
        period: '2026Q1',
        period_start: '2026-01-01',
        period_end: '2026-03-31',
        value: '164.22',
        unit: '$',
        as_of: '2026-03-15',
      },
    },
  ],
};

const RECOVERED_RESPONSE: ChatResponse = {
  ...QTD_RESPONSE,
  request_id: 'req-2',
  trace: [
    {
      index: 1,
      tool: 'get_qtd_estimate',
      arguments: { ticker: 'SHIELD', kpi: 'Units Sold' },
      status: 'error',
      duration_ms: 7,
      error_code: 'ambiguous_company',
      truncated: false,
    },
    {
      index: 2,
      tool: 'get_qtd_estimate',
      arguments: { ticker: 'SHLD', kpi: 'Units Sold' },
      status: 'ok',
      duration_ms: 8,
      error_code: null,
      truncated: false,
    },
  ],
};

function mockFetch(response: ChatResponse) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => response });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('asking a question', () => {
  test('shows suggested prompts before anything is asked', () => {
    mockFetch(QTD_RESPONSE);
    render(<App />);

    expect(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' })).toBeInTheDocument();
  });

  test('a suggestion asks its question and renders the answer', async () => {
    const fetchMock = mockFetch(QTD_RESPONSE);
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    expect(await screen.findByText(/quarter-to-date for 2026Q1 is 164\.22/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat',
      expect.objectContaining({ body: JSON.stringify({ question: 'ACME quarter-to-date ASP' }) }),
    );
  });

  test('the keyboard alone can submit a question', async () => {
    mockFetch(QTD_RESPONSE);
    render(<App />);

    await userEvent.type(screen.getByLabelText('Ask about a company KPI'), "ACME's QTD ASP{Enter}");

    expect(await screen.findByText(/quarter-to-date for 2026Q1 is 164\.22/)).toBeInTheDocument();
    expect(screen.getByText("ACME's QTD ASP")).toBeInTheDocument();
  });

  test('Shift+Enter adds a line instead of submitting', async () => {
    const fetchMock = mockFetch(QTD_RESPONSE);
    render(<App />);
    const input = screen.getByLabelText('Ask about a company KPI');

    await userEvent.type(input, 'ACME{Shift>}{Enter}{/Shift}ASP');

    expect(input).toHaveValue('ACME\nASP');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('an empty question cannot be submitted', () => {
    mockFetch(QTD_RESPONSE);
    render(<App />);

    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
  });

  test('a loading state is shown while the answer is pending', async () => {
    let release: (value: unknown) => void = () => {};
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(
        new Promise((resolve) => {
          release = resolve;
        }),
      ),
    );
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Querying the KPI database');
    release({ ok: true, json: async () => QTD_RESPONSE });
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });
});

describe('failures', () => {
  test('a service failure is reported with its message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: { code: 'timeout', message: 'The service timed out.' } }),
      }),
    );
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('The service timed out.');
  });

  test('a network failure does not leave the UI stuck', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    render(<App />);

    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('offline');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('the data panel', () => {
  test('shows the value with its unit, period, and QTD badge', async () => {
    mockFetch(QTD_RESPONSE);
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    const card = await screen.findByLabelText('ASP ($) quarter to date');
    expect(within(card).getByText('QTD')).toBeInTheDocument();
    expect(within(card).getByText('164.22')).toBeInTheDocument();
    expect(within(card).getByText('$')).toBeInTheDocument();
    expect(within(card).getByText('2026Q1')).toBeInTheDocument();
    expect(within(card).getByText('2026-03-15')).toBeInTheDocument();
  });
});

describe('the activity panel', () => {
  test('is collapsed until it is expanded', async () => {
    mockFetch(QTD_RESPONSE);
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    const toggle = await screen.findByRole('button', { name: /1 tool call/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/ticker: "ACME"/)).not.toBeVisible();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/ticker: "ACME"/)).toBeVisible();
    expect(screen.getByText('get_qtd_estimate')).toBeVisible();
    expect(screen.getByText('9 ms')).toBeVisible();
    expect(screen.getByText('req-1')).toBeVisible();
  });

  test('names the error code of a call that was recovered', async () => {
    mockFetch(RECOVERED_RESPONSE);
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: 'ACME quarter-to-date ASP' }));

    await userEvent.click(await screen.findByRole('button', { name: /2 tool calls, 1 recovered/ }));

    expect(screen.getByText('ambiguous_company')).toBeVisible();
    expect(screen.getByText(/ticker: "SHIELD"/)).toBeVisible();
    expect(screen.getByText(/ticker: "SHLD"/)).toBeVisible();
  });
});
