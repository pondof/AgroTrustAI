import { DossieTable } from "@/components/dashboard/DossieTable";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { StatsRow } from "@/components/dashboard/StatsRow";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDossies } from "@/hooks/useDossies";
import { useStats } from "@/hooks/useStats";

export function DashboardPage() {
  const stats = useStats();
  const dossies = useDossies({ page: 1, limit: 8 });
  const items = dossies.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Visão geral das subscrições do tenant.</p>
      </div>

      <StatsRow stats={stats.data} isLoading={stats.isLoading} />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-base">Dossiês Recentes</CardTitle>
          </CardHeader>
          <CardContent>
            <DossieTable items={items} isLoading={dossies.isLoading} />
          </CardContent>
        </Card>

        <RecentActivity items={items} />
      </div>
    </div>
  );
}
