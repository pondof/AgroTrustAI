"""AgroTrust AI – SecurityGuardAgent."""

from __future__ import annotations

import asyncio

import structlog
from pydantic import BaseModel

from agents.base import AgentExecutionError, BaseAgent, XAIFactor
from agents.security.schemas import SecurityInput, SecurityOutput
from agents.security.tools import (
    detect_deepfake,
    run_liveness_check,
    verify_title_blockchain,
)

logger = structlog.get_logger(__name__)


def _compute_fraud_risk(
    liveness_passed: bool,
    deepfake_prob: float,
    voice_clone_prob: float,
) -> str:
    """
    Lógica explícita de cálculo de risco — sem ML black-box nesta etapa.

    critical:  deepfake > 0.8 OU liveness falhou
    high:      deepfake > 0.5 OU voice_clone > 0.5
    medium:    deepfake > 0.3
    low:       demais casos
    """
    if not liveness_passed or deepfake_prob > 0.8:
        return "critical"
    if deepfake_prob > 0.5 or voice_clone_prob > 0.5:
        return "high"
    if deepfake_prob > 0.3:
        return "medium"
    return "low"


class SecurityGuardAgent(BaseAgent):
    """
    Agente de segurança / KYC.
    Roda liveness, deepfake detection e blockchain em paralelo.
    """

    MODEL_VERSION = "security-mock-0.1.0"

    async def run(self, input_data: BaseModel) -> SecurityOutput:
        if not isinstance(input_data, SecurityInput):
            raise TypeError(f"Esperava SecurityInput, recebeu {type(input_data)}")

        sec_input: SecurityInput = input_data
        log = logger.bind(
            correlation_id=sec_input.correlation_id,
            dossie_id=sec_input.dossie_id,
        )
        log.info("security_agent_started")

        try:
            liveness_res, deepfake_res, blockchain_res = await asyncio.gather(
                run_liveness_check(sec_input.session_id),
                detect_deepfake(sec_input.media_url),
                verify_title_blockchain(sec_input.car_number, sec_input.owner_cpf_hash),
            )
        except Exception as exc:
            log.error("security_agent_failed", error=str(exc))
            raise AgentExecutionError(
                correlation_id=sec_input.correlation_id,
                agent_name="SecurityGuardAgent",
                original_exception=exc,
            ) from exc

        fraud_risk = _compute_fraud_risk(
            liveness_passed=liveness_res.passed,
            deepfake_prob=deepfake_res.deepfake_probability,
            voice_clone_prob=deepfake_res.voice_clone_probability,
        )

        kyc_passed = (
            liveness_res.passed
            and deepfake_res.deepfake_probability < 0.5
            and deepfake_res.voice_clone_probability < 0.5
            and blockchain_res.verified
        )

        xai = self._build_xai_rationale(
            decision=f"fraud_risk={fraud_risk} kyc={kyc_passed}",
            factors=[
                XAIFactor(
                    name="liveness_score",
                    weight=0.35,
                    value=liveness_res.score,
                    impact="positive" if liveness_res.passed else "negative",
                ),
                XAIFactor(
                    name="deepfake_probability",
                    weight=0.35,
                    value=deepfake_res.deepfake_probability,
                    impact="negative" if deepfake_res.deepfake_probability > 0.3 else "positive",
                ),
                XAIFactor(
                    name="voice_clone_probability",
                    weight=0.15,
                    value=deepfake_res.voice_clone_probability,
                    impact="negative" if deepfake_res.voice_clone_probability > 0.5 else "positive",
                ),
                XAIFactor(
                    name="blockchain_title_verified",
                    weight=0.15,
                    value=blockchain_res.verified,
                    impact="positive" if blockchain_res.verified else "negative",
                ),
            ],
            confidence=0.97 if fraud_risk in {"critical", "low"} else 0.85,
        )

        log.info(
            "security_agent_completed",
            fraud_risk=fraud_risk,
            kyc_passed=kyc_passed,
            liveness=liveness_res.passed,
        )

        return SecurityOutput(
            dossie_id=sec_input.dossie_id,
            liveness_passed=liveness_res.passed,
            deepfake_probability=deepfake_res.deepfake_probability,
            voice_clone_probability=deepfake_res.voice_clone_probability,
            digital_mask_probability=deepfake_res.digital_mask_probability,
            title_verified_on_blockchain=blockchain_res.verified,
            blockchain_tx_hash=blockchain_res.tx_hash,
            fraud_risk_level=fraud_risk,
            kyc_passed=kyc_passed,
            xai_rationale=xai,
        )
