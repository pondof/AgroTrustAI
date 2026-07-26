/**
 * Tipos TypeScript espelhando os schemas Pydantic do backend (gateway + report).
 * Fonte da verdade: services/gateway/routes.py, routes_params.py e core/*.
 * Nenhum `any` — campos desconhecidos usam `unknown`.
 */

export type DossieStatus = "initiated" | "approved" | "rejected" | "manual_review" | string;
export type Verdict = "approved" | "rejected" | "manual_review";

// ─── Auth ─────────────────────────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  token_type: string;
  scopes: string[];
  tenant_id: string;
}

/** Sessão derivada do token (mantida apenas em memória). */
export interface Session {
  token: string;
  tenantId: string;
  scopes: string[];
  username: string;
}

// ─── Subscriptions ─────────────────────────────────────────────────────────────

export interface PropertyLocation {
  latitude: number;
  longitude: number;
  municipio: string;
  estado: string;
  biome?: string | null;
}

export interface SubscriptionRequest {
  producer_cpf_hash: string;
  car_number: string;
  property_area_ha: number;
  location: PropertyLocation;
  credit_amount_brl: number;
  credit_purpose: string;
  requested_by: string;
}

export interface SubscriptionResponse {
  dossie_id: string;
  status: string;
  correlation_id: string;
  submitted_at: string;
}

export interface DossieListItem {
  dossie_id: string;
  tenant_id: string;
  status: DossieStatus;
  verdict: Verdict | null;
  car_number: string;
  producer_cpf_hash: string;
  credit_amount_brl: number;
  credit_purpose: string;
  composite_score: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DossieListResponse {
  items: DossieListItem[];
  total: number;
  page: number;
  pages: number;
}

export interface DossieDetail {
  dossie_id: string;
  tenant_id: string;
  status: DossieStatus;
  verdict: Verdict | null;
  car_number: string;
  credit_amount_brl: number;
  credit_purpose: string;
  property_area_ha: number;
  composite_score: number | null;
  esg_score: number | null;
  financial_score: number | null;
  security_score: number | null;
  approved_amount_brl: number | null;
  rejection_reasons: string[];
  xai_summary: XaiScores;
  processing_time_ms: number | null;
  created_at: string | null;
  updated_at: string | null;
}

// ─── XAI ───────────────────────────────────────────────────────────────────────

export interface XaiScores {
  esg?: number;
  financial?: number;
  security?: number;
  composite?: number;
}

export interface XaiFactor {
  name: string;
  weight: number;
  value: string | number;
  impact: string | number;
}

export interface ShapData {
  shap_values: Record<string, number>;
  base_value?: number;
}

export interface AgentRationale {
  decision?: string;
  factors?: XaiFactor[];
  confidence?: number;
  shap?: ShapData;
}

export interface XaiConsolidatedRationale {
  scores?: XaiScores;
  esg_rationale?: AgentRationale;
  financial_rationale?: AgentRationale;
  security_rationale?: AgentRationale;
  [key: string]: unknown;
}

export interface XaiBreakdownEntry {
  score: number | null;
  rationale?: AgentRationale;
  verdict?: string | null;
  rejection_reasons?: string[];
}

export interface XaiDetail {
  dossie_id: string;
  verdict: Verdict | null;
  composite_score: number | null;
  rationale: XaiConsolidatedRationale;
  breakdown: Record<string, XaiBreakdownEntry>;
}

// ─── Audit ─────────────────────────────────────────────────────────────────────

export interface AuditTrailEntry {
  event_id: string;
  timestamp: string;
  event_type: string;
  subject: string;
  tenant_id: string;
  resource_id: string;
  outcome: string;
  details: Record<string, unknown>;
  previous_hash: string;
  entry_hash: string;
  /** String canônica que o backend hasheou (SHA-3-256) → recomputada no cliente. */
  canonical: string;
}

export interface AuditTrailResponse {
  dossie_id: string;
  entries: AuditTrailEntry[];
  total: number;
}

// ─── Params ────────────────────────────────────────────────────────────────────

export interface RiskParams {
  tenant_id: string;
  w_esg: number;
  w_financial: number;
  w_security: number;
  approve_threshold: number;
  manual_threshold: number;
  max_dti: number;
  max_credit_multiplier: number;
  updated_by: string;
}

export interface RiskParamsRequest {
  w_esg: number;
  w_financial: number;
  w_security: number;
  approve_threshold: number;
  manual_threshold: number;
  max_dti: number;
  max_credit_multiplier: number;
}

// ─── Stats ─────────────────────────────────────────────────────────────────────

export interface DossieStats {
  tenant_id: string;
  total: number;
  approved: number;
  rejected: number;
  manual_review: number;
  avg_processing_ms: number | null;
  avg_composite_score: number | null;
}
