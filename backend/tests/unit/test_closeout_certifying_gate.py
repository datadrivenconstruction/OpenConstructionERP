# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the closeout certifying-artifact gate.

These pin :func:`app.modules.closeout.service._generated_slot_delivered`, the
pure decision behind the handover readiness fix: a generated artifact is never
delivered before the package is built, a *certifying* artifact (punch-closure
report, final-inspection certificate) is delivered only while the live work it
certifies is complete, and a non-certifying export (COBie) is delivered once
built. ``outstanding=None`` is the build-manifest path, which reports every
generated artifact as present regardless of live site state.
"""

from app.modules.closeout.service import _CERTIFYING_ARTIFACTS, _generated_slot_delivered


class TestNotBuilt:
    def test_nothing_delivered_before_build(self) -> None:
        for artifact in ("punch_closure_report", "inspection_cert_pdf", "cobie_xlsx", None):
            assert _generated_slot_delivered(artifact, has_built=False, outstanding=None) is False
            assert _generated_slot_delivered(artifact, has_built=False, outstanding={"punch": 0}) is False


class TestBuildManifestPath:
    def test_outstanding_none_reports_present_once_built(self) -> None:
        # The build assembling its own manifest passes outstanding=None: every
        # generated artifact it writes reads as present regardless of live work.
        for artifact in ("punch_closure_report", "inspection_cert_pdf", "cobie_xlsx"):
            assert _generated_slot_delivered(artifact, has_built=True, outstanding=None) is True


class TestNonCertifyingArtifact:
    def test_cobie_export_delivered_once_built(self) -> None:
        # COBie is a data export, not a certificate; live counts never gate it.
        assert _generated_slot_delivered("cobie_xlsx", has_built=True, outstanding={"punch": 9}) is True

    def test_unknown_generated_artifact_delivered_once_built(self) -> None:
        assert _generated_slot_delivered("some_future_export", has_built=True, outstanding={"punch": 9}) is True


class TestCertifyingGate:
    def test_punch_report_blocked_while_punch_open(self) -> None:
        assert _generated_slot_delivered("punch_closure_report", has_built=True, outstanding={"punch": 3}) is False

    def test_punch_report_delivered_when_punch_clear(self) -> None:
        assert _generated_slot_delivered("punch_closure_report", has_built=True, outstanding={"punch": 0}) is True

    def test_inspection_cert_blocked_while_inspection_open(self) -> None:
        out = {"inspection": 2}
        assert _generated_slot_delivered("inspection_cert_pdf", has_built=True, outstanding=out) is False

    def test_inspection_cert_delivered_when_inspections_pass(self) -> None:
        out = {"inspection": 0}
        assert _generated_slot_delivered("inspection_cert_pdf", has_built=True, outstanding=out) is True

    def test_missing_counter_key_treated_as_zero(self) -> None:
        # A certifying artifact whose counter is absent from the map defaults to
        # zero outstanding, so it is delivered rather than falsely blocked.
        assert _generated_slot_delivered("punch_closure_report", has_built=True, outstanding={}) is True

    def test_each_certifying_artifact_maps_to_a_counter(self) -> None:
        assert _CERTIFYING_ARTIFACTS == {
            "punch_closure_report": "punch",
            "inspection_cert_pdf": "inspection",
        }
        # COBie must never be a certifying artifact (it is a data export).
        assert "cobie_xlsx" not in _CERTIFYING_ARTIFACTS
