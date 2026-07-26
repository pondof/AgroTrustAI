import { api } from "./client";

/** Solicita o PDF de compliance ao gateway (que faz proxy do report-service). */
export async function requestReport(dossieId: string): Promise<Blob> {
  const { data } = await api.post<Blob>(`/v1/reports/${dossieId}`, null, {
    responseType: "blob",
    headers: { Accept: "application/pdf" },
  });
  return data;
}

/** Dispara o download de um Blob no browser (cria/limpa um <a> temporário). */
export function downloadReport(blob: Blob, dossieId: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `agrotrust_${dossieId}.pdf`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
