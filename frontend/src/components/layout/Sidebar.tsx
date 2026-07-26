import { FileText, LayoutDashboard, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { NavLink } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  requiredScope?: string;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/dossies", label: "Dossiês", icon: FileText },
  { to: "/params", label: "Parâmetros", icon: SlidersHorizontal, requiredScope: "admin:params" },
  { to: "/audit", label: "Auditoria", icon: ShieldCheck, requiredScope: "audit:read" },
];

export function Sidebar() {
  const { hasScope } = useAuth();
  const items = NAV_ITEMS.filter((item) => !item.requiredScope || hasScope(item.requiredScope));

  return (
    <aside className="hidden w-60 shrink-0 border-r bg-card md:flex md:flex-col">
      <div className="flex h-16 items-center gap-2 border-b px-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
          A
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold">AgroTrust AI</div>
          <div className="text-[10px] text-muted-foreground">Subscrição de Crédito</div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 p-3">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              )
            }
          >
            <Icon className="h-4 w-4" aria-hidden />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="border-t p-3 text-[10px] text-muted-foreground">
        Fase 3 · Ambiente de desenvolvimento
      </div>
    </aside>
  );
}
