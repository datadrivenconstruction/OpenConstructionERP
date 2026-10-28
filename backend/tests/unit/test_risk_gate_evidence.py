"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The risk register reports to the governance gate."""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.risk import evidence

LINK = ("risk", "p")


def _risk(code: str, *, status: str = "open", tier: str = "low", owner: str = "A", plan: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        code=code, status=status, risk_tier=tier, owner_name=owner, owner_user_id=None, mitigation_strategy=plan
    )


def _states(risks: list[SimpleNamespace]) -> dict[str, tuple[str, str]]:
    return {i.code: (i.state, i.detail) for i in evidence.items_for(risks, LINK)}


def test_open_risk_without_owner_or_plan_is_not_met() -> None:
    out = _states([_risk("R1", owner=""), _risk("R2", tier="critical")])
    assert out["risk.owners_assigned"] == ("not_met", "R1")
    assert out["risk.serious_mitigated"] == ("not_met", "R2")


def test_closed_risks_and_low_tiers_are_not_asked() -> None:
    out = _states([_risk("R1", status="closed", owner="", tier="critical"), _risk("R2", tier="medium")])
    assert out["risk.owners_assigned"][0] == "met"
    assert out["risk.serious_mitigated"][0] == "met"


def test_provider_is_registered_non_blocking() -> None:
    from app.modules.project_governance.evidence import evidence_providers

    evidence.register_gate_evidence()
    reg = next(p for p in evidence_providers() if p.name == evidence.PROVIDER_NAME)
    assert reg.blocking is False
