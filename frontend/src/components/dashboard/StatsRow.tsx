import { CheckCircle2, ClipboardList, FileStack, XCircle } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import type { DossieStats } from "@/types";
import { cn } from "@/lib/utils";

interface StatsRowProps {
  stats?: DossieStats;
  isLoading?: boolean;
}

const CARDS = [
  { key: "total", label: "Total", icon: FileStack, color: "text-primary", bg: "bg-primary/10" },
  { key: "approved", label: "Aprovados", icon: CheckCircle2, color: "text-emerald-600", bg: "bg-emerald-500/10" },
  { key: "rejected", label: "Rejeitados", icon: XCircle, color: "text-red-600", bg: "bg-red-500/10" },
  {
    key: "manual_review",
    label: "Análise Manual",
    icon: ClipboardList,
    color: "text-orange-600",
    bg: "bg-orange-500/10",
  },
] as const;

export function StatsRow({ stats, isLoading }: StatsRowProps) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {CARDS.map(({ key, label, icon: Icon, color, bg }) => (
        <Card key={key}>
          <CardContent className="flex items-center gap-4 p-4">
            <div className={cn("flex h-11 w-11 items-center justify-center rounded-lg", bg, color)}>
              <Icon className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
              <div className="text-2xl font-bold tabular-nums">
                {isLoading ? "…" : (stats?.[key] ?? 0)}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
