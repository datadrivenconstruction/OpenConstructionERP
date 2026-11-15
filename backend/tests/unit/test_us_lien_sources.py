"""Every US lien statute reference carries a verified official source or verified: false."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from app.modules.us_ca_pack.config import STATE_RULES as CA_RULES
from app.modules.us_pack.billing_forms import STATUTORY_WAIVER_STATES
from app.modules.us_tx_pack.config import STATE_RULES as TX_RULES

_PATH = Path(__file__).resolve().parents[2] / "app/core/country_data/us_lien_sources.json"
_OFFICIAL_HOSTS = (".gov", ".us")


def _entries() -> dict[str, dict]:
    data = json.loads(_PATH.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["entries"]}


def _lien_codes(config: dict) -> list[str]:
    return [item["code"] for item in config.get("lien", [])]


def test_every_entry_is_verified_with_official_source_or_flagged():
    for id_, e in _entries().items():
        assert isinstance(e["verified"], bool), id_
        assert e.get("citation"), id_
        if e["verified"]:
            host = urlparse(e["source_url"]).hostname or ""
            assert host.endswith(_OFFICIAL_HOSTS), f"{id_}: not an official host"
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date_verified"]), id_
        else:
            assert "source_url" not in e, id_


def test_every_lien_deadline_and_waiver_state_has_an_entry():
    entries = _entries()
    codes = [c for cfg in (CA_RULES, TX_RULES) for c in _lien_codes(cfg)]
    assert codes, "lien blocks not found in state pack configs"
    for code in codes:
        assert f"lien:{code}" in entries, code
    for state in STATUTORY_WAIVER_STATES:
        assert f"waiver:{state}" in entries, state
