"""The onboarding cost base job hands on the language the base opened in.

A fresh base switches its work items to its own language after the import. When
that switch does not land the job still succeeds, so the only way the wizard can
say the text stayed in English is if the job state carries both languages.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.onboarding.router import _job_state


def _row(result: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id="j1",
        kind="onboarding.load_cwicr",
        status="success",
        result_jsonb=result,
        payload_jsonb={"db_id": "ZH_CHINA"},
        error_jsonb=None,
        progress_percent=100,
        created_at=None,
        completed_at=None,
    )


def test_job_state_carries_the_text_languages() -> None:
    state = _job_state(
        _row(
            {
                "imported": 10486,
                "total_items": 10486,
                "text_language": "en",
                "text_language_requested": "zh",
                "text_language_error": "GitHub unreachable",
            }
        )
    )
    assert state.text_language == "en"
    assert state.text_language_requested == "zh"
    assert state.text_language_error == "GitHub unreachable"
    assert state.outcome == "completed"


def test_job_state_without_languages_leaves_them_empty() -> None:
    state = _job_state(_row({"imported": 5}))
    assert state.text_language is None
    assert state.text_language_requested is None
