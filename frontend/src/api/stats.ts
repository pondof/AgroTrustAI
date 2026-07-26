import type { DossieStats } from "@/types";

import { api } from "./client";

export async function getStats(): Promise<DossieStats> {
  const { data } = await api.get<DossieStats>("/v1/stats");
  return data;
}
