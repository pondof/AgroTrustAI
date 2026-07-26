import { useQuery } from "@tanstack/react-query";

import { getStats } from "@/api/stats";
import type { DossieStats } from "@/types";

export const statsKeys = {
  all: ["stats"] as const,
};

export function useStats() {
  return useQuery<DossieStats>({
    queryKey: statsKeys.all,
    queryFn: getStats,
  });
}
