import { useRef, type FormEvent, type KeyboardEvent } from 'react';

const MAX_QUESTION_LENGTH = 500;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  pending: boolean;
}

/**
 * The question input.
 *
 * Enter submits and Shift+Enter adds a line, which is what a keyboard-driven
 * reader expects from a chat box.
 */
export default function Composer({ value, onChange, onSubmit, pending }: ComposerProps) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const canSubmit = value.trim().length > 0 && !pending;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (canSubmit) {
      onSubmit();
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) {
        onSubmit();
      }
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <label className="visually-hidden" htmlFor="question">
        Ask about a company KPI
      </label>
      <textarea
        id="question"
        ref={textarea}
        className="composer__input"
        rows={2}
        maxLength={MAX_QUESTION_LENGTH}
        placeholder="Ask about a company KPI, for example: ACME quarter-to-date ASP"
        value={value}
        disabled={pending}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="composer__actions">
        <span className="composer__hint">Enter to send, Shift+Enter for a new line</span>
        <button type="submit" className="composer__submit" disabled={!canSubmit}>
          {pending ? 'Asking…' : 'Ask'}
        </button>
      </div>
    </form>
  );
}
