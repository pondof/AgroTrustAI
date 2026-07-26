import { Navigate, Outlet, useLocation } from "react-router-dom";

import { AppLayout } from "@/components/layout/AppLayout";
import { useAuth } from "@/hooks/useAuth";

/**
 * Exige sessão autenticada. Sem token (ex.: após reload — o JWT vive só em memória),
 * redireciona para /login guardando a rota de origem. Autenticado, renderiza o layout.
 */
export function RequireAuth() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <AppLayout />;
}

/** Exige um scope específico; caso contrário volta ao dashboard. */
export function RequireScope({ scope }: { scope: string }) {
  const { hasScope } = useAuth();
  if (!hasScope(scope)) {
    return <Navigate to="/" replace />;
  }
  return <Outlet />;
}
