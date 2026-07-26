import type {
  AuditTrailResponse,
  DossieDetail,
  DossieListResponse,
  SubscriptionRequest,
  SubscriptionResponse,
  XaiDetail,
} from "@/types";

import { api } from "./client";

export interface ListDossiesParams {
  page?: number;
  limit?: number;
  status?: string;
  verdict?: string;
}

export async function getAllDossies(params: ListDossiesParams = {}): Promise<DossieListResponse> {
  const { data } = await api.get<DossieListResponse>("/v1/subscriptions", {
    params: {
      page: params.page ?? 1,
      limit: params.limit ?? 20,
      status: params.status || undefined,
      verdict: params.verdict || undefined,
    },
  });
  return data;
}

export async function getDossie(dossieId: string): Promise<DossieDetail> {
  const { data } = await api.get<DossieDetail>(`/v1/subscriptions/${dossieId}`);
  return data;
}

export async function getDossieXai(dossieId: string): Promise<XaiDetail> {
  const { data } = await api.get<XaiDetail>(`/v1/subscriptions/${dossieId}/xai`);
  return data;
}

export async function getAuditTrail(dossieId: string): Promise<AuditTrailResponse> {
  const { data } = await api.get<AuditTrailResponse>(`/v1/subscriptions/${dossieId}/audit-trail`);
  return data;
}

export async function createDossie(body: SubscriptionRequest): Promise<SubscriptionResponse> {
  const { data } = await api.post<SubscriptionResponse>("/v1/subscriptions", body);
  return data;
}
