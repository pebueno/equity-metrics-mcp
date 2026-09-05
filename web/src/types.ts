/** Wire types for the chat endpoint. These mirror the FastAPI response models. */

export interface ToolTraceItem {
  index: number;
  tool: string;
  arguments: Record<string, unknown>;
  status: 'ok' | 'error';
  duration_ms: number;
  error_code: string | null;
  truncated: boolean;
}

export interface ToolPayloadItem {
  tool: string;
  data: Record<string, unknown>;
}

export interface ChatResponse {
  answer: string;
  request_id: string;
  provider: string;
  model: string;
  prompt_version: string;
  iterations: number;
  duration_ms: number;
  created_at: string;
  trace: ToolTraceItem[];
  data: ToolPayloadItem[];
}

/** A company as every tool reports it. */
export interface CompanySummary {
  ticker: string;
  company_name: string;
  sector: string;
}

/** One historical estimate. Values are strings so decimal precision survives. */
export interface EstimatePoint {
  period: string;
  period_start: string;
  period_end: string;
  value: string;
  unit: string;
}

export interface HistoricalEstimates {
  company: CompanySummary;
  kpi: string;
  unit: string;
  estimates: EstimatePoint[];
}

export interface QtdEstimate {
  company: CompanySummary;
  kpi: string;
  period: string;
  period_start: string;
  period_end: string;
  value: string;
  unit: string;
  as_of: string;
}

export interface CompanyKpis {
  company: CompanySummary;
  kpis: { kpi: string; unit: string }[];
}

export interface CompanySearchResult {
  query: string;
  companies: CompanySummary[];
}

/** One entry in the conversation pane. */
export type Turn =
  | { kind: 'question'; id: string; text: string }
  | { kind: 'answer'; id: string; response: ChatResponse }
  | { kind: 'failure'; id: string; message: string };
