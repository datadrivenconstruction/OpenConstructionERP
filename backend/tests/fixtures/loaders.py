"""Test fixture loaders for the EAC v2 platform tests (RFC 35)."""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent


def load_eac_rule_valid(name: str) -> dict:
    """Load a valid EAC rule fixture by file name (e.g. '01_aggregate_external_walls_volume.json')."""
    return json.loads((FIXTURES_ROOT / "eac" / "valid_rules" / name).read_text(encoding="utf-8"))


def load_eac_rule_invalid(name: str) -> dict:
    """Load an invalid EAC rule fixture (parses as JSON but is semantically invalid)."""
    return json.loads((FIXTURES_ROOT / "eac" / "invalid_rules" / name).read_text(encoding="utf-8"))


def load_bim_canonical(name: str) -> dict:
    """Load a canonical-format BIM sample by file name (e.g. 'sample_walls_only.json')."""
    return json.loads((FIXTURES_ROOT / "bim_canonical" / name).read_text(encoding="utf-8"))


def list_ids_samples() -> list[Path]:
    """Return all IDS XML sample files sorted by name."""
    return sorted((FIXTURES_ROOT / "ids").glob("ids_*.xml"))


def list_eac_rules_valid() -> list[Path]:
    """Return all valid EAC rule fixtures sorted by name."""
    return sorted((FIXTURES_ROOT / "eac" / "valid_rules").glob("*.json"))


def list_eac_rules_invalid() -> list[Path]:
    """Return all invalid EAC rule fixtures sorted by name."""
    return sorted((FIXTURES_ROOT / "eac" / "invalid_rules").glob("*.json"))


def ids_xsd_path() -> Path:
    """Return the path to the IDS-1.0.xsd schema."""
    return FIXTURES_ROOT / "ids" / "IDS-1.0.xsd"


def schedules_dir() -> Path:
    """Return the schedules fixtures directory."""
    return FIXTURES_ROOT / "schedules"
