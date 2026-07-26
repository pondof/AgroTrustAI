import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  status: string;
  className?: string;
}

interface StatusStyle {
  label: string;
  badge: string;
  dot: string;
}

/** Mapeia status/veredicto do dossiê para rótulo pt-BR + cores acessíveis. */
export function statusStyle(status: string): StatusStyle {
  switch (status) {
    case "approved":
      return {
        label: "Aprovado",
        badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
        dot: "bg-emerald-500",
      };
    case "rejected":
      return {
        label: "Reprovado",
        badge: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
        dot: "bg-red-500",
      };
    case "manual_review":
      return {
        label: "Análise Manual",
        badge: "bg-orange-100 text-orange-800 dark:bg-orange-950 dark:text-orange-300",
        dot: "bg-orange-500",
      };
    case "initiated":
      return {
        label: "Iniciado",
        badge: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
        dot: "bg-slate-400",
      };
    default:
      return {
        label: status,
        badge: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
        dot: "bg-slate-400",
      };
  }
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const style = statusStyle(status);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        style.badge,
        className,
      )}
      data-testid={`status-badge-${status}`}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", style.dot)} aria-hidden />
      {style.label}
    </span>
  );
}
