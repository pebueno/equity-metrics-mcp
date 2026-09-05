import { useEffect, useState } from 'react';

import { fetchHealth } from './api';

type ApiState = { kind: 'loading' } | { kind: 'ready'; env: string } | { kind: 'error' };

/** Application shell. The investor chat experience lands here in milestone 5. */
export default function App() {
  const [apiState, setApiState] = useState<ApiState>({ kind: 'loading' });

  useEffect(() => {
    let cancelled = false;
    fetchHealth()
      .then((health) => {
        if (!cancelled) setApiState({ kind: 'ready', env: health.app_env });
      })
      .catch(() => {
        if (!cancelled) setApiState({ kind: 'error' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>EquityMetrics</h1>
        <p>Curated quarterly KPI estimates for public companies.</p>
      </header>
      <p className="status-line">{describe(apiState)}</p>
    </main>
  );
}

function describe(state: ApiState): string {
  switch (state.kind) {
    case 'loading':
      return 'Checking API…';
    case 'ready':
      return `API reachable (${state.env})`;
    case 'error':
      return 'API unreachable';
  }
}
