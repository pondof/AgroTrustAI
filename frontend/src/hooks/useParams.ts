import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getParams, putParams } from "@/api/params";
import type { RiskParams, RiskParamsRequest } from "@/types";

export const paramsKeys = {
  all: ["params"] as const,
};

export function useRiskParams() {
  return useQuery<RiskParams>({
    queryKey: paramsKeys.all,
    queryFn: getParams,
  });
}

export function useUpdateParams() {
  const queryClient = useQueryClient();
  return useMutation<RiskParams, unknown, RiskParamsRequest>({
    mutationFn: putParams,
    onSuccess: (data) => {
      queryClient.setQueryData(paramsKeys.all, data);
    },
  });
}
