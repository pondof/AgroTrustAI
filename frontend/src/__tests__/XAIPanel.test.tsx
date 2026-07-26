import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { XAIPanel } from "@/components/xai/XAIPanel";
import { renderWithProviders } from "@/test/utils";
import type { XaiDetail } from "@/types";

const XAI: XaiDetail = {
  dossie_id: "DOS-1",
  verdict: "approved",
  composite_score: 762,
  rationale: {
    scores: { esg: 720, financial: 810, security: 655, composite: 762 },
    esg_rationale: {
      decision: "approved",
      confidence: 0.9,
      factors: [{ name: "CAR regular", weight: 0.4, value: "regular", impact: "positive" }],
    },
    financial_rationale: {
      decision: "approved",
      factors: [{ name: "DTI", weight: 0.5, value: 0.42, impact: -0.2 }],
      shap: { shap_values: { renda: 0.3, dti: -0.1 }, base_value: 0.5 },
    },
    security_rationale: { decision: "approved", confidence: 0.88, factors: [] },
  },
  breakdown: {
    esg: { score: 720, rationale: {} },
    financial: { score: 810, rationale: {} },
    security: { score: 655, rationale: {} },
    composite: { score: 762, verdict: "approved", rejection_reasons: [] },
  },
};

describe("XAIPanel", () => {
  it("renderiza as abas Composto/ESG/Financeiro/Segurança", () => {
    renderWithProviders(<XAIPanel xai={XAI} />, { withRouter: false });
    expect(screen.getByRole("tab", { name: "Composto" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "ESG" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Financeiro" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Segurança" })).toBeInTheDocument();
  });

  it("mostra o veredicto na aba composta (default)", () => {
    renderWithProviders(<XAIPanel xai={XAI} />, { withRouter: false });
    expect(screen.getByText("Aprovado")).toBeInTheDocument();
    expect(screen.getByText("Contribuição por agente")).toBeInTheDocument();
  });
});
