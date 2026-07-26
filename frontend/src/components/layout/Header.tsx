import { Building2, LogOut, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";

function initials(username: string): string {
  const name = username.split("@")[0] ?? username;
  return name.slice(0, 2).toUpperCase();
}

export function Header() {
  const { session, logout } = useAuth();
  const [dark, setDark] = useState<boolean>(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
  }, [dark]);

  return (
    <header className="flex h-16 items-center justify-between border-b bg-card px-4 md:px-6">
      <div className="flex items-center gap-2 text-sm font-semibold md:hidden">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
          A
        </div>
        AgroTrust AI
      </div>

      <div className="ml-auto flex items-center gap-3">
        {session && (
          <span className="hidden items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs font-medium text-muted-foreground sm:inline-flex">
            <Building2 className="h-3.5 w-3.5" aria-hidden />
            {session.tenantId}
          </span>
        )}

        <Button
          variant="ghost"
          size="icon"
          aria-label={dark ? "Ativar tema claro" : "Ativar tema escuro"}
          onClick={() => setDark((v) => !v)}
        >
          {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>

        {session && (
          <div className="flex items-center gap-2">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary"
              title={session.username}
            >
              {initials(session.username)}
            </div>
            <Button variant="ghost" size="sm" onClick={logout} className="gap-1.5">
              <LogOut className="h-4 w-4" />
              <span className="hidden sm:inline">Sair</span>
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}
