import { screen } from "@testing-library/react";
import { sha3_256 } from "js-sha3";
import { describe, expect, it } from "vitest";

import { AuditTimeline } from "@/components/audit/AuditTimeline";
import { renderWithProviders } from "@/test/utils";
import type { AuditTrailEntry } from "@/types";

function entry(overrides: Partial<AuditTrailEntry> & { canonical: string }): AuditTrailEntry {
  const base: AuditTrailEntry = {
    event_id: overrides.event_id ?? `evt-${overrides.canonical}`,
    timestamp: "2026-07-23T10:00:00Z",
    event_type: "system.agent_invoked",
    subject: "svc",
    tenant_id: "coop-demo",
    resource_id: "DOS-1",
    outcome: "success",
    details: {},
    previous_hash: "prev",
    canonical: overrides.canonical,
    // Por padrão o hash confere (recomputado do canonical).
    entry_hash: sha3_256(overrides.canonical),
  };
  return { ...base, ...overrides };
}

describe("AuditTimeline", () => {
  it("renderiza eventos com o mais recente no topo e o hash conferido", () => {
    const older = entry({
      canonical: "{\"a\":1}",
      event_type: "subscription.initiated",
      timestamp: "2026-07-23T10:00:00Z",
    });
    const newer = entry({
      canonical: "{\"b\":2}",
      event_type: "subscription.approved",
      timestamp: "2026-07-23T11:00:00Z",
    });

    // O backend retorna em ordem de inserção (antigo → recente).
    renderWithProviders(<AuditTimeline entries={[older, newer]} />, { withRouter: false });

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("subscription.approved"); // mais recente no topo
    expect(items[1]).toHaveTextContent("subscription.initiated");

    // Ambas as entradas conferem o SHA-3-256 recomputado no cliente.
    expect(screen.getAllByTestId("hash-verified")).toHaveLength(2);
    expect(screen.getByText(/Cadeia íntegra/)).toBeInTheDocument();
  });

  it("marca como inválida uma entrada com hash adulterado", () => {
    const tampered = entry({ canonical: "{\"a\":1}", entry_hash: "deadbeef" });
    renderWithProviders(<AuditTimeline entries={[tampered]} />, { withRouter: false });

    expect(screen.getByTestId("hash-invalid")).toBeInTheDocument();
    expect(screen.getByText(/Atenção/)).toBeInTheDocument();
  });
});
