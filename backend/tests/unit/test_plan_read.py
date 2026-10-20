# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - vision-LLM plan reading core (issue #194).

Covers the deterministic half of the vision plan reader: the structured-output
parsing and rejection, the scale plausibility belt and inferred-confidence
floor, the normalized-to-PDF-point round-trip, the DPI clamp, the run FSM, and
the human-confirm / B8 invariant that the server owns every number.

The vision call is ALWAYS stubbed - no test makes a real API call. Pure-Python
where possible (stub repos + ``SimpleNamespace``); the few service-method tests
swap a fake repo onto a bare ``TakeoffService`` instance so no DB is touched.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.takeoff import plan_read as pr

# A1 page in PDF points: 594 x 841 mm -> 1684 x 2384 pt (1mm = 72/25.4 pt).
A1_W_PT = 594.0 * 72.0 / 25.4
A1_H_PT = 841.0 * 72.0 / 25.4


# ---------------------------------------------------------------------------
# Vision capability
# ---------------------------------------------------------------------------


class TestVisionCapability:
    def test_anthropic_is_vision_capable(self) -> None:
        assert pr.is_vision_capable("anthropic", "claude-sonnet-4-6") is True

    def test_openai_gpt41_is_vision_capable(self) -> None:
        assert pr.is_vision_capable("openai", "gpt-4.1") is True

    def test_gemini_is_vision_capable(self) -> None:
        assert pr.is_vision_capable("gemini", "gemini-2.5-flash") is True

    def test_non_vision_provider_is_not_capable(self) -> None:
        # Ollama / local runtimes are not in VISION_PROVIDERS.
        assert pr.is_vision_capable("ollama", "llama3.1") is False
        assert pr.is_vision_capable("deepseek", "deepseek-chat") is False

    def test_text_only_model_on_vision_provider_is_not_capable(self) -> None:
        assert pr.is_vision_capable("openai", "gpt-3.5-turbo") is False
        assert pr.is_vision_capable("openai", "text-embedding-3-large") is False

    def test_unknown_model_on_vision_provider_is_capable(self) -> None:
        assert pr.is_vision_capable("anthropic", "some-future-model") is True


# ---------------------------------------------------------------------------
# DPI clamp and coordinate mapping
# ---------------------------------------------------------------------------


class TestRasterGeometry:
    def test_a1_downscales_to_clamped_dpi(self) -> None:
        # A1 long edge 2384 pt at target 2000 px -> ~60 dpi, clamped up to 72.
        dpi = pr.clamp_dpi(A1_H_PT, 2000)
        assert dpi == 72

    def test_small_a4_upscales(self) -> None:
        # A4 short detail (210 mm = 595 pt) upscales above the 72 floor.
        a4_long = 297.0 * 72.0 / 25.4  # 841 pt
        dpi = pr.clamp_dpi(a4_long, 2000)
        assert dpi > 72
        assert dpi <= 300

    def test_dpi_never_exceeds_max(self) -> None:
        assert pr.clamp_dpi(10.0, 2000) == 300

    def test_norm_point_round_trips_to_pdf_points(self) -> None:
        x, y = pr.norm_to_pdf_point(0.5, 0.25, A1_W_PT, A1_H_PT)
        assert x == pytest.approx(A1_W_PT * 0.5)
        assert y == pytest.approx(A1_H_PT * 0.25)

    def test_norm_point_clamped_to_page(self) -> None:
        # An overshoot (1.2) can never push a vertex off the page.
        x, _ = pr.norm_to_pdf_point(1.2, -0.1, A1_W_PT, A1_H_PT)
        assert x == pytest.approx(A1_W_PT)

    def test_polygon_round_trip_area(self) -> None:
        # A 0.3 x 0.3 normalized rectangle -> a known PDF-point area.
        poly = [
            {"x": 0.1, "y": 0.1},
            {"x": 0.4, "y": 0.1},
            {"x": 0.4, "y": 0.4},
            {"x": 0.1, "y": 0.4},
        ]
        pts = pr.norm_polygon_to_pdf_points(poly, A1_W_PT, A1_H_PT)
        expected = (0.3 * A1_W_PT) * (0.3 * A1_H_PT)
        assert pr.shoelace_area(pts) == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# Scale derivation, plausibility belt, inferred floor
# ---------------------------------------------------------------------------


class TestScale:
    def test_derive_ratio_from_dimension_string(self) -> None:
        # 0.2 normalized x-span on A1 = 0.2 * 1684 pt = 336.8 pt across 4.10 m.
        p1 = pr.norm_to_pdf_point(0.1, 0.5, A1_W_PT, A1_H_PT)
        p2 = pr.norm_to_pdf_point(0.3, 0.5, A1_W_PT, A1_H_PT)
        ratio = pr.derive_scale_ratio(p1, p2, 4.10, "m")
        assert ratio == pytest.approx((0.2 * A1_W_PT) / 4.10, rel=1e-6)

    def test_absurd_ratio_rejected_by_plausibility_belt(self) -> None:
        # 1 px = 1000 m: a near-zero pixel span over a huge real distance.
        p1 = pr.norm_to_pdf_point(0.0, 0.5, A1_W_PT, A1_H_PT)
        p2 = pr.norm_to_pdf_point(0.001, 0.5, A1_W_PT, A1_H_PT)
        ratio = pr.derive_scale_ratio(p1, p2, 1000.0, "m")
        assert ratio is not None
        assert pr.scale_is_plausible(ratio, A1_W_PT, A1_H_PT) is False

    def test_realistic_ratio_passes_belt(self) -> None:
        p1 = pr.norm_to_pdf_point(0.1, 0.5, A1_W_PT, A1_H_PT)
        p2 = pr.norm_to_pdf_point(0.3, 0.5, A1_W_PT, A1_H_PT)
        ratio = pr.derive_scale_ratio(p1, p2, 4.10, "m")
        assert pr.scale_is_plausible(ratio, A1_W_PT, A1_H_PT) is True

    def test_inferred_scale_gets_confidence_floor(self) -> None:
        capped = pr.clamp_inferred_confidence("inferred", 0.95)
        assert capped == pytest.approx(pr.INFERRED_SCALE_MAX_CONFIDENCE)

    def test_measured_scale_keeps_its_confidence(self) -> None:
        assert pr.clamp_inferred_confidence("dimension_string", 0.95) == 0.95

    def test_unit_conversion_to_metres(self) -> None:
        assert pr.unit_to_metres(4100.0, "mm") == pytest.approx(4.1)
        assert pr.unit_to_metres(1.0, "ft") == pytest.approx(0.3048)


# ---------------------------------------------------------------------------
# Choosing the ratio the proposals are measured in
# ---------------------------------------------------------------------------

# A 1:50 drawing on A1: one metre is about 56.7 PDF points, so the sheet spans
# roughly 42 m. Enter the reference in millimetres by mistake and the ratio comes
# out a thousand times smaller, which claims the sheet is 42 km across.
CALIBRATION_1_50 = 56.7
CALIBRATION_OFF_BY_MM = CALIBRATION_1_50 / 1000.0


def _detected_scale() -> SimpleNamespace:
    """A model-read scale: 0.2 of the A1 width standing for 4.10 m."""
    return SimpleNamespace(
        ref_pixels=(SimpleNamespace(x=0.1, y=0.5), SimpleNamespace(x=0.3, y=0.5)),
        ref_real_value=4.10,
        ref_unit="m",
        unit="m",
    )


class TestScaleResolution:
    """The user's calibration wins, but it no longer skips the belt.

    A model-derived scale is already belted in ``parse_plan_read_response``, so
    by the time a ratio is chosen only the calibration can still be absurd. It
    gets squared into every room area, which is why an unchecked one produces
    quantities that are wrong by six orders of magnitude and look ordinary.
    """

    def test_a_sane_calibration_is_used_as_given(self) -> None:
        ratio, dropped = pr.resolve_scale_ratio(CALIBRATION_1_50, None, A1_W_PT, A1_H_PT)
        assert ratio == CALIBRATION_1_50
        assert dropped is None

    def test_a_calibration_off_by_a_factor_of_a_thousand_is_refused(self) -> None:
        ratio, dropped = pr.resolve_scale_ratio(CALIBRATION_OFF_BY_MM, None, A1_W_PT, A1_H_PT)
        assert ratio is None, "measuring at this ratio would inflate every area a millionfold"
        assert dropped == "scale:implausible_calibration"

    def test_a_refused_calibration_is_not_swapped_for_the_model_reading(self) -> None:
        """Silently measuring at a ratio the user never chose is the worse failure.

        Empty values send them back to the calibration tool. A plausible number
        derived from a scale they did not pick reads as though their own
        calibration had been honoured.
        """
        ratio, dropped = pr.resolve_scale_ratio(CALIBRATION_OFF_BY_MM, _detected_scale(), A1_W_PT, A1_H_PT)
        assert ratio is None
        assert dropped == "scale:implausible_calibration"

    def test_the_model_reading_is_used_when_nobody_calibrated(self) -> None:
        ratio, dropped = pr.resolve_scale_ratio(None, _detected_scale(), A1_W_PT, A1_H_PT)
        assert ratio == pytest.approx((0.2 * A1_W_PT) / 4.10, rel=1e-6)
        assert dropped is None

    def test_no_scale_at_all_is_silence_not_a_complaint(self) -> None:
        """Rooms without a scale are the ordinary outcome, not a problem to report."""
        assert pr.resolve_scale_ratio(None, None, A1_W_PT, A1_H_PT) == (None, None)


# ---------------------------------------------------------------------------
# Structured-output parsing and per-item rejection
# ---------------------------------------------------------------------------


def _good_response() -> dict[str, Any]:
    return {
        "scale": {
            "ref_pixels": [[0.1, 0.5], [0.3, 0.5]],
            "ref_real_value": 4.10,
            "ref_unit": "m",
            "source": "dimension_string",
            "confidence": 0.82,
        },
        "rooms": [
            {
                "name": "Kitchen",
                "polygon": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]],
                "confidence": 0.74,
            }
        ],
        "symbols": [{"element_class": "door", "centers": [[0.2, 0.2], [0.5, 0.5], [0.6, 0.6]], "confidence": 0.6}],
    }


class TestParsing:
    def _parse(self, resp: Any) -> tuple[Any, list[str]]:
        return pr.parse_plan_read_response(resp, page=1, page_width_pt=A1_W_PT, page_height_pt=A1_H_PT)

    def test_good_response_parses_clean(self) -> None:
        result, dropped = self._parse(_good_response())
        assert dropped == []
        assert len(result.rooms) == 1
        assert len(result.symbols) == 1
        assert result.scale is not None

    def test_non_object_response_is_rejected_not_crashed(self) -> None:
        result, dropped = self._parse(["not", "an", "object"])
        assert dropped == ["response_not_an_object"]
        assert result.rooms == []

    def test_none_response_is_rejected_not_crashed(self) -> None:
        result, dropped = self._parse(None)
        assert "response_not_an_object" in dropped
        assert result.scale is None

    def test_out_of_bounds_room_vertex_is_dropped(self) -> None:
        bad = _good_response()
        bad["rooms"][0]["polygon"][0] = [1.5, 0.1]  # x > 1 -> NormPoint rejects
        result, dropped = self._parse(bad)
        assert "room:schema" in dropped
        assert len(result.rooms) == 0

    def test_nan_coordinate_is_dropped(self) -> None:
        bad = _good_response()
        bad["rooms"][0]["polygon"][0] = [float("nan"), 0.1]
        result, dropped = self._parse(bad)
        assert "room:schema" in dropped
        assert len(result.rooms) == 0

    def test_degenerate_two_vertex_room_is_dropped(self) -> None:
        bad = _good_response()
        bad["rooms"][0]["polygon"] = [[0.1, 0.1], [0.4, 0.4]]  # < 3 vertices
        result, dropped = self._parse(bad)
        assert "room:schema" in dropped
        assert len(result.rooms) == 0

    def test_one_bad_room_does_not_poison_the_rest(self) -> None:
        resp = _good_response()
        resp["rooms"].append({"name": "Bad", "polygon": [[2.0, 2.0]], "confidence": 0.9})
        result, dropped = self._parse(resp)
        assert len(result.rooms) == 1  # the good one survived
        assert "room:schema" in dropped

    def test_absurd_scale_is_dropped_to_none(self) -> None:
        resp = _good_response()
        resp["scale"] = {
            "ref_pixels": [[0.0, 0.5], [0.001, 0.5]],
            "ref_real_value": 1000.0,
            "ref_unit": "m",
            "source": "dimension_string",
            "confidence": 0.9,
        }
        result, dropped = self._parse(resp)
        assert result.scale is None
        assert "scale:implausible" in dropped

    def test_inferred_scale_confidence_floored_in_parse(self) -> None:
        resp = _good_response()
        resp["scale"]["source"] = "inferred"
        resp["scale"]["confidence"] = 0.95
        result, _ = self._parse(resp)
        assert result.scale.confidence <= pr.INFERRED_SCALE_MAX_CONFIDENCE

    def test_zero_rooms_is_honest_empty_not_error(self) -> None:
        resp = {"scale": None, "rooms": [], "symbols": []}
        result, dropped = self._parse(resp)
        assert result.rooms == []
        assert dropped == []  # an honest empty is not a dropped item


# ---------------------------------------------------------------------------
# Service-level run: FSM, B8 (server owns the number), no-key, non-vision
# ---------------------------------------------------------------------------


class _FakeRunRepo:
    """In-memory AiTakeoffRun repository for service tests."""

    def __init__(self) -> None:
        self.runs: dict[uuid.UUID, Any] = {}
        self.spend = 0.0

    async def create(self, run: Any) -> Any:
        if getattr(run, "id", None) is None:
            run.id = uuid.uuid4()
        self.runs[run.id] = run
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> Any:
        return self.runs.get(run_id)

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        run = self.runs.get(run_id)
        for k, v in fields.items():
            setattr(run, k, v)

    async def rolling_spend_usd(self, _user_id: uuid.UUID, *, window_hours: int = 24) -> float:
        return self.spend


class _FakeMeasurementRepo:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.updated: dict[uuid.UUID, dict] = {}

    async def create_bulk(self, measurements: list[Any]) -> list[Any]:
        for m in measurements:
            if getattr(m, "id", None) is None:
                m.id = uuid.uuid4()
        self.created.extend(measurements)
        return measurements

    async def list_proposals_for_run(self, _run_id: uuid.UUID) -> list[Any]:
        return list(self.created)

    async def update_fields(self, measurement_id: uuid.UUID, **fields: object) -> None:
        self.updated[measurement_id] = dict(fields)
        for m in self.created:
            if getattr(m, "id", None) == measurement_id:
                for k, v in fields.items():
                    setattr(m, k, v)


class _FakeDocRepo:
    def __init__(self, doc: Any) -> None:
        self._doc = doc

    async def get_by_id(self, _doc_id: uuid.UUID) -> Any:
        return self._doc


def _make_service(*, run_repo, meas_repo, doc_repo):
    from app.modules.takeoff.service import TakeoffService

    svc = object.__new__(TakeoffService)
    svc.session = SimpleNamespace()
    svc.repo = doc_repo
    svc.measurement_repo = meas_repo
    svc.plan_read_repo = run_repo
    return svc


def _run_row(**kw: Any) -> Any:
    base = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "document_id": str(uuid.uuid4()),
        "page": 1,
        "mode": "rooms",
        "user_id": uuid.uuid4(),
        "status": "queued",
        "scale_pixels_per_unit": None,
        "provider": None,
        "model_used": None,
        "total_tokens": 0,
        "cost_usd_estimate": 0.0,
        "duration_ms": 0,
        "proposal_count": 0,
        "accepted_count": 0,
        "validation_report": None,
        "failure_reason": None,
        "do_cost_match": False,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _patch_provider(monkeypatch, *, vision: bool = True, model: str = "claude-sonnet-4-6") -> None:
    """Force the service's provider resolution to a known vision provider."""

    async def _resolve(_self, _user_id):  # noqa: ANN001, ANN202
        provider = "anthropic" if vision else "ollama"
        return provider, "sk-test", None, model

    from app.modules.takeoff.service import TakeoffService

    monkeypatch.setattr(TakeoffService, "_resolve_plan_read_provider", _resolve)


def _patch_rasterize(monkeypatch) -> None:
    """Stub rasterize_page so no PDF / PDF reader is needed."""

    def _raster(_content, _page, *, target_long_edge_px=2000):  # noqa: ANN001, ANN202, ARG001
        return (b"\x89PNG-stub", "image/png", 150, A1_W_PT, A1_H_PT)

    monkeypatch.setattr(pr, "rasterize_page", _raster)


def _patch_call_ai(monkeypatch, response: dict[str, Any], *, tokens: int = 1500) -> dict[str, int]:
    """Stub call_ai to return a canned JSON response. Returns a call counter."""
    import json

    from app.modules.ai import ai_client as _ac

    counter = {"calls": 0}

    async def _fake(**_kwargs: Any) -> tuple[str, int]:
        counter["calls"] += 1
        return json.dumps(response), tokens

    monkeypatch.setattr(_ac, "call_ai", _fake)
    # The service imports call_ai locally inside _run_plan_read, so patching the
    # module attribute is what takes effect.
    return counter


@pytest.mark.asyncio
async def test_run_reaches_review_with_proposals(monkeypatch, tmp_path) -> None:
    """A good response drives the FSM to review and persists proposals."""
    _patch_rasterize(monkeypatch)
    _patch_call_ai(monkeypatch, _good_response())

    doc = SimpleNamespace(file_path=str(tmp_path / "x.pdf"), pages=3)
    (tmp_path / "x.pdf").write_bytes(b"%PDF-1.4 stub")
    run_repo = _FakeRunRepo()
    meas_repo = _FakeMeasurementRepo()
    svc = _make_service(run_repo=run_repo, meas_repo=meas_repo, doc_repo=_FakeDocRepo(doc))
    _patch_provider(monkeypatch)

    run = _run_row()
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    assert run.status == "review"
    assert run.proposal_count == 2  # one room + one symbol
    assert run.failure_reason is None
    # Proposals are persisted as proposed, ai_plan_read, with a confidence.
    assert all(m.review_status == "proposed" for m in meas_repo.created)
    assert all(m.source == "ai_plan_read" for m in meas_repo.created)
    assert all(m.confidence is not None for m in meas_repo.created)


@pytest.mark.asyncio
async def test_zero_rooms_reaches_review_not_failed(monkeypatch, tmp_path) -> None:
    """A model that finds nothing is honest-empty (review), never failed."""
    _patch_rasterize(monkeypatch)
    _patch_call_ai(monkeypatch, {"scale": None, "rooms": [], "symbols": []})

    doc = SimpleNamespace(file_path=str(tmp_path / "x.pdf"), pages=1)
    (tmp_path / "x.pdf").write_bytes(b"%PDF stub")
    run_repo = _FakeRunRepo()
    meas_repo = _FakeMeasurementRepo()
    svc = _make_service(run_repo=run_repo, meas_repo=meas_repo, doc_repo=_FakeDocRepo(doc))
    _patch_provider(monkeypatch)

    run = _run_row()
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    assert run.status == "review"
    assert run.proposal_count == 0
    assert meas_repo.created == []


@pytest.mark.asyncio
async def test_b8_server_owns_the_number(monkeypatch, tmp_path) -> None:
    """A fabricated model area is ignored; the shoelace recompute wins."""
    _patch_rasterize(monkeypatch)
    resp = _good_response()
    # The room has a real 0.3 x 0.3 normalized box. Even if the model claimed a
    # giant area elsewhere, the persisted value is the server's shoelace number
    # divided by scale^2 - the model never supplies the area at all.
    resp["rooms"][0]["area_m2"] = 999999.0  # an ignored, unmodelled field
    _patch_call_ai(monkeypatch, resp)

    doc = SimpleNamespace(file_path=str(tmp_path / "x.pdf"), pages=1)
    (tmp_path / "x.pdf").write_bytes(b"%PDF stub")
    run_repo = _FakeRunRepo()
    meas_repo = _FakeMeasurementRepo()
    svc = _make_service(run_repo=run_repo, meas_repo=meas_repo, doc_repo=_FakeDocRepo(doc))
    _patch_provider(monkeypatch)

    # Give the run a known scale so a real value is computed.
    poly = pr.norm_polygon_to_pdf_points(
        [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}, {"x": 0.1, "y": 0.4}],
        A1_W_PT,
        A1_H_PT,
    )
    scale = 50.0  # pdf points per metre
    expected_area = pr.shoelace_area(poly) / (scale * scale)

    run = _run_row(scale_pixels_per_unit=scale)
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    room = next(m for m in meas_repo.created if m.type == "area")
    assert float(room.measurement_value) == pytest.approx(expected_area, rel=1e-6)
    assert float(room.measurement_value) != pytest.approx(999999.0)


@pytest.mark.asyncio
async def test_self_intersecting_room_capped_to_low_band(monkeypatch, tmp_path) -> None:
    """A self-intersecting room is capped to low confidence regardless of the
    model score, and stamped with an error verdict for the accept block."""
    _patch_rasterize(monkeypatch)
    bowtie = {
        "scale": None,
        "rooms": [
            {
                "name": "Bowtie",
                # A bowtie / figure-eight: edges cross.
                "polygon": [[0.1, 0.1], [0.4, 0.4], [0.4, 0.1], [0.1, 0.4]],
                "confidence": 0.95,
            }
        ],
        "symbols": [],
    }
    _patch_call_ai(monkeypatch, bowtie)

    doc = SimpleNamespace(file_path=str(tmp_path / "x.pdf"), pages=1)
    (tmp_path / "x.pdf").write_bytes(b"%PDF stub")
    run_repo = _FakeRunRepo()
    meas_repo = _FakeMeasurementRepo()
    svc = _make_service(run_repo=run_repo, meas_repo=meas_repo, doc_repo=_FakeDocRepo(doc))
    _patch_provider(monkeypatch)

    run = _run_row()
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    room = meas_repo.created[0]
    from app.modules.takeoff.schemas import TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD

    assert room.confidence < TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD
    assert room.metadata_["verdict"] == "error"


@pytest.mark.asyncio
async def test_rate_limit_provider_error_marks_run_failed(monkeypatch, tmp_path) -> None:
    """A provider rate-limit error fails the run with a rate_limited reason."""
    _patch_rasterize(monkeypatch)

    from app.modules.ai import ai_client as _ac

    async def _boom(**_kwargs: Any) -> tuple[str, int]:
        raise ValueError("AI rate limit exceeded (anthropic). Please wait a moment.")

    monkeypatch.setattr(_ac, "call_ai", _boom)

    doc = SimpleNamespace(file_path=str(tmp_path / "x.pdf"), pages=1)
    (tmp_path / "x.pdf").write_bytes(b"%PDF stub")
    run_repo = _FakeRunRepo()
    svc = _make_service(run_repo=run_repo, meas_repo=_FakeMeasurementRepo(), doc_repo=_FakeDocRepo(doc))
    _patch_provider(monkeypatch)

    run = _run_row()
    run_repo.runs[run.id] = run
    await svc._run_plan_read(run.id, user_id=str(run.user_id))

    assert run.status == "failed"
    assert run.failure_reason == "rate_limited"


# ---------------------------------------------------------------------------
# Degradation: no key / non-vision provider -> 400
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    @pytest.mark.asyncio
    async def test_no_key_raises_400(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from app.modules.ai import ai_client as _ac
        from app.modules.takeoff.service import TakeoffService

        def _no_key(_settings, _preferred=None):  # noqa: ANN001, ANN202
            raise ValueError("No AI API key configured.")

        monkeypatch.setattr(_ac, "resolve_provider_key_model", _no_key)

        svc = object.__new__(TakeoffService)
        svc.session = SimpleNamespace()

        async def _get_by_user_id(_uid):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(
            "app.modules.ai.repository.AISettingsRepository.get_by_user_id",
            staticmethod(_get_by_user_id),
        )
        with pytest.raises(HTTPException) as exc:
            await svc._resolve_plan_read_provider(str(uuid.uuid4()))
        assert exc.value.status_code == 400
        assert "No AI provider" in exc.value.detail

    @pytest.mark.asyncio
    async def test_non_vision_provider_raises_400(self, monkeypatch) -> None:
        from fastapi import HTTPException

        from app.modules.ai import ai_client as _ac
        from app.modules.takeoff.service import TakeoffService

        def _ollama(_settings, _preferred=None):  # noqa: ANN001, ANN202
            return "ollama", "", None

        monkeypatch.setattr(_ac, "resolve_provider_key_model", _ollama)

        svc = object.__new__(TakeoffService)
        svc.session = SimpleNamespace()

        async def _get_by_user_id(_uid):  # noqa: ANN001, ANN202
            return None

        monkeypatch.setattr(
            "app.modules.ai.repository.AISettingsRepository.get_by_user_id",
            staticmethod(_get_by_user_id),
        )
        with pytest.raises(HTTPException) as exc:
            await svc._resolve_plan_read_provider(str(uuid.uuid4()))
        assert exc.value.status_code == 400
        assert "image analysis" in exc.value.detail

    @pytest.mark.asyncio
    async def test_meta_reports_unavailable_without_a_key(self, monkeypatch) -> None:
        """meta never raises on a missing key - it reports vision_available=False."""
        from fastapi import HTTPException

        from app.modules.takeoff.service import TakeoffService

        async def _raise(_self, _user_id):  # noqa: ANN001, ANN202
            raise HTTPException(status_code=400, detail="No AI provider configured.")

        monkeypatch.setattr(TakeoffService, "_resolve_plan_read_provider", _raise)

        run_repo = _FakeRunRepo()
        svc = object.__new__(TakeoffService)
        svc.session = SimpleNamespace()
        svc.plan_read_repo = run_repo

        meta = await svc.plan_read_meta(str(uuid.uuid4()))
        assert meta["vision_available"] is False
        assert meta["reason"] is not None
        # Thresholds are still reported so the UI can render bands.
        assert meta["confidence_high_threshold"] == 0.78
        assert meta["confidence_medium_threshold"] == 0.62
