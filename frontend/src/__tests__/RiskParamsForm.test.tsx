import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskParamsForm } from "@/components/params/RiskParamsForm";
import { renderWithProviders } from "@/test/utils";
import type { RiskParams } from "@/types";

const INITIAL: RiskParams = {
  tenant_id: "coop-demo",
  w_esg: 0.35,
  w_financial: 0.45,
  w_security: 0.2,
  approve_threshold: 600,
  manual_threshold: 450,
  max_dti: 0.65,
  max_credit_multiplier: 12,
  updated_by: "gestor@agrotrust.ai",
};

function saveButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /Salvar parâmetros/i }) as HTMLButtonElement;
}

describe("RiskParamsForm", () => {
  it("habilita salvar quando os pesos somam 1.00", () => {
    renderWithProviders(<RiskParamsForm initial={INITIAL} />);
    expect(saveButton()).not.toBeDisabled();
    expect(screen.getByText(/= 1\.00 ✓/)).toBeInTheDocument();
  });

  it("desabilita salvar quando a soma dos pesos ≠ 1.00", () => {
    renderWithProviders(<RiskParamsForm initial={INITIAL} />);
    const esg = screen.getByRole("spinbutton", { name: "Peso ESG" });

    fireEvent.change(esg, { target: { value: "0.5" } }); // soma 1.15
    expect(saveButton()).toBeDisabled();
    expect(screen.getByText(/deve somar 1\.00/)).toBeInTheDocument();

    fireEvent.change(esg, { target: { value: "0.35" } }); // volta a somar 1.00
    expect(saveButton()).not.toBeDisabled();
  });

  it("mostra a prévia do veredicto conforme os thresholds", () => {
    renderWithProviders(<RiskParamsForm initial={INITIAL} />);
    // Score de teste padrão é 650 (>= 600) → APROVADO.
    expect(screen.getByText("APROVADO")).toBeInTheDocument();
  });
});
