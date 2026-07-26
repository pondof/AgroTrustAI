import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";

import { RequireAuth, RequireScope } from "@/components/auth/RouteGuards";
import { AuthProvider } from "@/context/AuthContext";
import { AuditIndexPage } from "@/pages/AuditIndexPage";
import { AuditPage } from "@/pages/AuditPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DossieDetailPage } from "@/pages/DossieDetailPage";
import { DossiesPage } from "@/pages/DossiesPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { ParamsPage } from "@/pages/ParamsPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/dossies" element={<DossiesPage />} />
              <Route path="/dossies/:dossieId" element={<DossieDetailPage />} />
              <Route path="/dossies/:dossieId/audit" element={<AuditPage />} />
              <Route path="/audit" element={<AuditIndexPage />} />
              <Route element={<RequireScope scope="admin:params" />}>
                <Route path="/params" element={<ParamsPage />} />
              </Route>
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
          <Toaster richColors position="top-right" closeButton />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
