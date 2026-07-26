import type { RiskParams, RiskParamsRequest } from "@/types";

import { api } from "./client";

export async function getParams(): Promise<RiskParams> {
  const { data } = await api.get<RiskParams>("/v1/params");
  return data;
}

export async function putParams(body: RiskParamsRequest): Promise<RiskParams> {
  const { data } = await api.put<RiskParams>("/v1/params", body);
  return data;
}
