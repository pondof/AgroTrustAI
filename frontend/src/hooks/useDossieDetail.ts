import { useQuery } from "@tanstack/react-query";

import { getAuditTrail, getDossie, getDossieXai } from "@/api/dossies";
import type { AuditTrailResponse, DossieDetail, XaiDetail } from "@/types";

import { dossieKeys } from "./useDossies";

export function useDossieDetail(dossieId: string) {
  return useQuery<DossieDetail>({
    queryKey: dossieKeys.detail(dossieId),
    queryFn: () => getDossie(dossieId),
    enabled: Boolean(dossieId),
  });
}

export function useDossieXai(dossieId: string) {
  return useQuery<XaiDetail>({
    queryKey: dossieKeys.xai(dossieId),
    queryFn: () => getDossieXai(dossieId),
    enabled: Boolean(dossieId),
  });
}

export function useAuditTrail(dossieId: string) {
  return useQuery<AuditTrailResponse>({
    queryKey: dossieKeys.audit(dossieId),
    queryFn: () => getAuditTrail(dossieId),
    enabled: Boolean(dossieId),
  });
}
