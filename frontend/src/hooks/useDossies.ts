import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createDossie, getAllDossies, type ListDossiesParams } from "@/api/dossies";
import type { DossieListResponse, SubscriptionRequest, SubscriptionResponse } from "@/types";

export const dossieKeys = {
  all: ["dossies"] as const,
  list: (params: ListDossiesParams) => ["dossies", "list", params] as const,
  detail: (id: string) => ["dossies", "detail", id] as const,
  xai: (id: string) => ["dossies", "xai", id] as const,
  audit: (id: string) => ["dossies", "audit", id] as const,
};

export function useDossies(params: ListDossiesParams) {
  return useQuery<DossieListResponse>({
    queryKey: dossieKeys.list(params),
    queryFn: () => getAllDossies(params),
    placeholderData: (prev) => prev,
  });
}

export function useCreateDossie() {
  const queryClient = useQueryClient();
  return useMutation<SubscriptionResponse, unknown, SubscriptionRequest>({
    mutationFn: createDossie,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: dossieKeys.all });
    },
  });
}
