import type { ChatResponse } from './types';

export interface HealthResponse {
  status: string;
  app_env: string;
}

/** Fetch API liveness; the UI uses it to show whether the backend is reachable. */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/health');
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

/** Ask a question. Throws with a readable message so the UI can show the cause. */
export async function askQuestion(question: string, signal?: AbortSignal): Promise<ChatResponse> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as ChatResponse;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: unknown }).message);
    }
  } catch {
    // Fall through to the status-based message below.
  }
  return response.status >= 500
    ? 'The service could not answer right now. Try again in a moment.'
    : `Request failed with status ${response.status}.`;
}
