import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

interface ProvidersOptions {
  route?: string;
  withRouter?: boolean;
}

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", withRouter = true, ...options }: ProvidersOptions & RenderOptions = {},
) {
  const client = makeClient();
  function Wrapper({ children }: { children: ReactNode }) {
    const tree = <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    return withRouter ? <MemoryRouter initialEntries={[route]}>{tree}</MemoryRouter> : tree;
  }
  return render(ui, { wrapper: Wrapper, ...options });
}
