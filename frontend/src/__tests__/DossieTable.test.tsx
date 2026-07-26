import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DossieTable } from "@/components/dashboard/DossieTable";
import { renderWithProviders } from "@/test/utils";
import type { DossieListItem } from "@/types";

function item(overrides: Partial<DossieListItem>): DossieListItem {
  return {
    dossie_id: "DOS-1",
    tenant_id: "coop-demo",
    status: "initiated",
    verdict: null,
    car_number: "MT-1",
    producer_cpf_hash: "a".repeat(64),
    credit_amount_brl: 1000,
    credit_purpose: "custeio",
    composite_score: null,
    created_at: "2026-07-23T10:00:00Z",
    updated_at: "2026-07-23T10:00:00Z",
    ...overrides,
  };
}

describe("DossieTable", () => {
  it("mostra o StatusBadge correto por veredicto/status", () => {
    const items = [
      item({ dossie_id: "DOS-A", verdict: "approved", status: "approved", composite_score: 720 }),
      item({ dossie_id: "DOS-R", verdict: "rejected", status: "rejected", composite_score: 300 }),
      item({ dossie_id: "DOS-M", verdict: "manual_review", status: "manual_review", composite_score: 500 }),
      item({ dossie_id: "DOS-I", verdict: null, status: "initiated" }),
    ];
    renderWithProviders(<DossieTable items={items} />);

    expect(screen.getByText("Aprovado")).toBeInTheDocument();
    expect(screen.getByText("Reprovado")).toBeInTheDocument();
    expect(screen.getByText("Análise Manual")).toBeInTheDocument();
    expect(screen.getByText("Iniciado")).toBeInTheDocument();

    // O score composto aparece arredondado.
    expect(screen.getByText("720")).toBeInTheDocument();
    // Links para o detalhe.
    expect(screen.getByRole("link", { name: "DOS-A" })).toHaveAttribute("href", "/dossies/DOS-A");
  });

  it("mostra EmptyState quando não há dossiês", () => {
    renderWithProviders(<DossieTable items={[]} />);
    expect(screen.getByText("Nenhum dossiê encontrado")).toBeInTheDocument();
  });

  it("mostra o spinner quando carregando", () => {
    renderWithProviders(<DossieTable items={[]} isLoading />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
