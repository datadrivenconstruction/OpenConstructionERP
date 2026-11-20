"""Design module settings, read from the environment (``OE_DESIGN_*``)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DesignSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OE_DESIGN_", case_sensitive=False, extra="ignore")

    # Upload limit of one .ddcrev (contract §8 default: 2 GiB).
    revision_max_bytes: int = Field(default=2 * 1024**3, ge=1)
    # Sum of the uncompressed members of one package; bounds a zip bomb.
    revision_max_unpacked_bytes: int = Field(default=8 * 1024**3, ge=1)
    # manifest.json and diff.json are parsed in memory.
    revision_max_json_bytes: int = Field(default=64 * 1024**2, ge=1)
    # JSON chunk of geometry.glb (read whole to check node keys).
    revision_max_glb_json_bytes: int = Field(default=64 * 1024**2, ge=1)
    # Rows of elements.parquet; every row becomes an ERP element.
    revision_max_rows: int = Field(default=2_000_000, ge=1)
    # One autosaved browser-editor draft is kept in the database; bigger models go through the desktop intake.
    draft_max_bytes: int = Field(default=64 * 1024**2, ge=1)
    # An intake that died mid-way leaves an "uploading" row; older ones are swept.
    revision_stale_upload_seconds: int = Field(default=3600, ge=60)
    # AI handoff (R14). Endpoints for providers the ERP does not name itself:
    # OE_DESIGN_AI_ENDPOINTS='{"<provider>": {"protocol": "chat-completions|messages", "endpoint": "https://..."}}'
    ai_endpoints: dict[str, dict[str, str]] = Field(default_factory=dict)
    ai_profile_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    # Address the editor is told to call (in the .ddclink). Empty: the ERP's own frontend URL.
    # Never taken from the request: a forged Host header would send the one-time code elsewhere.
    public_url: str = ""
    # POST /link/exchange is unauthenticated; attempts per minute per client address.
    exchange_rate_per_minute: int = Field(default=30, ge=1)
    # MCP entry point POST /api/v1/design/mcp (R15). Off by default; each person must also switch MCP on.
    mcp_enabled: bool = False
    # Server worker (R13). Absolute path of the `ddc` binary; empty/missing = generation disabled.
    ddc_cli: str = ""
    # Both commands together; the process is killed after this.
    job_timeout_seconds: int = Field(default=1800, ge=1)
    # The worker writes a heartbeat this often; a running job silent for job_stale_seconds is declared lost.
    job_heartbeat_seconds: float = Field(default=5.0, gt=0)
    job_stale_seconds: int = Field(default=60, ge=1)
    # A queued job nobody picked up (queue down, ERP restarted) is failed after this.
    job_queue_wait_seconds: int = Field(default=600, ge=1)
    # Full browser editor (bundle ddc-web-editor/1), fetched on first use from the release feed ddc-web-release/1.
    # Empty feed URL = engine mode only (the small generator shipped in the module).
    web_feed_url: str = "https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionDesign/main/erp-link/release/latest-web.json"
    web_feed_ttl_seconds: int = Field(default=600, ge=10)
    # Minisign public key (the .pub file or its base64 line). Empty: the committed data/web-release.pub, if any;
    # with no key at all nothing is downloaded.
    web_release_pubkey: str = ""
    web_release_max_bytes: int = Field(default=200 * 1024**2, ge=1)
    web_release_max_unpacked_bytes: int = Field(default=800 * 1024**2, ge=1)
    web_download_timeout_seconds: int = Field(default=900, ge=10)
    # Where bundles are unpacked; empty = <app data dir>/design/web-editor. Never inside the package.
    web_editor_dir: str = ""


@lru_cache(maxsize=1)
def get_design_settings() -> DesignSettings:
    return DesignSettings()
