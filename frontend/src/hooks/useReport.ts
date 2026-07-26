import { useMutation } from "@tanstack/react-query";

import { downloadReport, requestReport } from "@/api/reports";

/** Mutation que gera o PDF e dispara o download no sucesso. */
export function useGenerateReport(dossieId: string) {
  return useMutation<Blob, unknown, void>({
    mutationFn: () => requestReport(dossieId),
    onSuccess: (blob) => downloadReport(blob, dossieId),
  });
}
