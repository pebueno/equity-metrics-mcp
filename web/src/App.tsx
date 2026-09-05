import { useCallback, useEffect, useRef, useState } from 'react';

import { askQuestion } from './api';
import ActivityPanel from './components/ActivityPanel';
import Composer from './components/Composer';
import DataPanel from './components/DataPanel';
import type { Turn } from './types';

/**
 * Prompts that exercise the paths worth showing first: a current-quarter
 * figure, a history, a company whose name is approximate, and one that cannot
 * be resolved without the reader choosing.
 */
const SUGGESTIONS = [
  'ACME quarter-to-date ASP',
  'Show ACME total revenue history',
  'What KPIs does CLD9 report?',
  'cloud revenue',
];

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const nextId = useRef(0);
  const liveRegion = useRef<HTMLDivElement>(null);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || pending) {
        return;
      }
      const id = String(nextId.current++);
      setTurns((current) => [...current, { kind: 'question', id, text: trimmed }]);
      setDraft('');
      setPending(true);

      try {
        const response = await askQuestion(trimmed);
        setTurns((current) => [...current, { kind: 'answer', id: `${id}-a`, response }]);
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Something went wrong.';
        setTurns((current) => [...current, { kind: 'failure', id: `${id}-e`, message }]);
      } finally {
        setPending(false);
      }
    },
    [pending],
  );

  useEffect(() => {
    // Guarded because jsdom, and some embedded browsers, do not implement it.
    const anchor = liveRegion.current;
    if (typeof anchor?.scrollIntoView === 'function') {
      anchor.scrollIntoView({ block: 'end' });
    }
  }, [turns, pending]);

  const started = turns.length > 0;

  return (
    <div className="app">
      <header className="app__header">
        <h1>EquityMetrics</h1>
        <p>Curated quarterly KPI estimates, answered from the database and nothing else.</p>
      </header>

      <main className="app__main">
        {!started && (
          <section className="empty" aria-label="Suggested questions">
            <h2 className="empty__title">Start with a question</h2>
            <ul className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  <button
                    type="button"
                    className="suggestion"
                    disabled={pending}
                    onClick={() => void ask(suggestion)}
                  >
                    {suggestion}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <ol className="conversation">
          {turns.map((turn) => (
            <li key={turn.id} className={`turn turn--${turn.kind}`}>
              {turn.kind === 'question' && <p className="question">{turn.text}</p>}

              {turn.kind === 'answer' && (
                <article className="answer">
                  {turn.response.answer.split('\n').map((line, index) => (
                    <p key={index} className="answer__line">
                      {line}
                    </p>
                  ))}
                  <DataPanel items={turn.response.data} />
                  <ActivityPanel response={turn.response} />
                </article>
              )}

              {turn.kind === 'failure' && (
                <p className="failure" role="alert">
                  {turn.message}
                </p>
              )}
            </li>
          ))}
        </ol>

        {pending && (
          <p className="pending" role="status">
            <span className="pending__dot" aria-hidden="true" />
            Querying the KPI database…
          </p>
        )}
        <div ref={liveRegion} />
      </main>

      <footer className="app__footer">
        <Composer
          value={draft}
          onChange={setDraft}
          onSubmit={() => void ask(draft)}
          pending={pending}
        />
      </footer>
    </div>
  );
}
