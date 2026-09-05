import { render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import App from './App';

afterEach(() => {
  vi.unstubAllGlobals();
});

test('reports the API environment once the health check resolves', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok', app_env: 'test' }) }),
  );

  render(<App />);

  expect(await screen.findByText('API reachable (test)')).toBeInTheDocument();
});

test('reports an unreachable API when the health check fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

  render(<App />);

  expect(await screen.findByText('API unreachable')).toBeInTheDocument();
});
