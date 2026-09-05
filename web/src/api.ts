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
