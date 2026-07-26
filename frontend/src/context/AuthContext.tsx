import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { login as loginRequest } from "@/api/auth";
import { setAuthToken, setUnauthorizedHandler } from "@/api/client";
import type { Session } from "@/types";

export interface AuthContextValue {
  session: Session | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  hasScope: (scope: string) => boolean;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Provedor de autenticação. O JWT é mantido SOMENTE em estado React (memória):
 * nunca em localStorage/sessionStorage/cookie. Consequência intencional: ao
 * recarregar a página a sessão é perdida e o usuário volta para /login.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);

  const logout = useCallback(() => {
    setSession(null);
    setAuthToken(null);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const token = await loginRequest(username, password);
    setAuthToken(token.access_token);
    setSession({
      token: token.access_token,
      tenantId: token.tenant_id,
      scopes: token.scopes,
      username,
    });
  }, []);

  const hasScope = useCallback(
    (scope: string) => session?.scopes.includes(scope) ?? false,
    [session],
  );

  // Registra o handler de 401 do axios → faz logout automaticamente.
  useEffect(() => {
    setUnauthorizedHandler(() => logout());
    return () => setUnauthorizedHandler(() => {});
  }, [logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: session !== null,
      login,
      logout,
      hasScope,
    }),
    [session, login, logout, hasScope],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
