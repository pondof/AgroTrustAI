import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Une classes Tailwind com merge inteligente (padrão shadcn/ui). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Formata um número como moeda BRL. */
export function formatBRL(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

/** Formata um timestamp ISO em data/hora local pt-BR. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(d);
}

/** Trunca um hash exibindo os primeiros `head` chars + reticências. */
export function truncateHash(hash: string, head = 12): string {
  if (!hash) return "—";
  return hash.length <= head ? hash : `${hash.slice(0, head)}…`;
}

/**
 * Mascara o hash do CPF exibindo apenas 8 chars + "***".
 * O CPF em claro NUNCA chega ao frontend; isto reforça a não-exposição do hash.
 */
export function maskCpfHash(hash: string | null | undefined): string {
  if (!hash) return "—";
  return `${hash.slice(0, 8)}***`;
}
