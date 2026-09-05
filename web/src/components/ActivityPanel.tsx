import { useId, useState } from 'react';

import type { ChatResponse, ToolTraceItem } from '../types';

/**
 * The collapsed record of how an answer was produced.
 *
 * Every tool call is listed in order with its sanitized arguments, outcome, and
 * duration, so a reader can audit the answer rather than trust it.
 */
export default function ActivityPanel({ response }: { response: ChatResponse }) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const failures = response.trace.filter((entry) => entry.status === 'error').length;

  return (
    <div className="activity">
      <button
        type="button"
        className="activity__toggle"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((open) => !open)}
      >
        <span className="activity__chevron" aria-hidden="true">
          {expanded ? '▾' : '▸'}
        </span>
        {summarize(response.trace, failures)}
      </button>

      <div id={panelId} className="activity__body" hidden={!expanded}>
        <ol className="activity__list">
          {response.trace.map((entry) => (
            <li key={entry.index} className="activity__item">
              <div className="activity__row">
                <span className="activity__index numeric">{entry.index}</span>
                <code className="activity__tool">{entry.tool}</code>
                <span className={`badge ${entry.status === 'ok' ? 'badge--ok' : 'badge--error'}`}>
                  {entry.status === 'ok' ? 'ok' : (entry.error_code ?? 'error')}
                </span>
                <span className="activity__duration numeric">{entry.duration_ms} ms</span>
              </div>
              <pre className="activity__args">{formatArguments(entry.arguments)}</pre>
              {entry.truncated && (
                <p className="activity__note">Result truncated to its size bound.</p>
              )}
            </li>
          ))}
        </ol>
        <dl className="activity__meta">
          <div>
            <dt>Request</dt>
            <dd className="numeric">{response.request_id}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>
              {response.provider} / {response.model}
            </dd>
          </div>
          <div>
            <dt>Prompt</dt>
            <dd>{response.prompt_version}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd className="numeric">{response.duration_ms} ms</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function summarize(trace: ToolTraceItem[], failures: number): string {
  const calls = `${trace.length} tool ${trace.length === 1 ? 'call' : 'calls'}`;
  return failures > 0 ? `${calls}, ${failures} recovered` : calls;
}

function formatArguments(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) {
    return 'no arguments';
  }
  return entries.map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join('\n');
}
