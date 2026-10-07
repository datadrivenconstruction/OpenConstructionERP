"""Separate-process real startup probe; invoked only with a private test cluster."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def run() -> None:
    # The parent sets BOTH supported environment spellings before imports:
    # every async/sync engine and data repair factory therefore uses its own
    # disposable cluster. cwd and data paths are also private temporary paths.
    # The legacy module-state resolver has no PostgreSQL data-root override.
    # Isolate that fallback too, before any application imports can read it.
    private_home = Path(os.environ["OE_DATA_DIR"]) / "test-home"
    private_home.mkdir()
    Path.home = classmethod(lambda cls: private_home)

    from sqlalchemy.engine import make_url

    from app import main
    from app.config import get_settings
    from app.core import embedded_pg, rls_setup
    from app.core.module_state import _resolve_data_dir
    from app.core.partner_pack.state import _resolve_state_dir
    from app.database import async_session_factory, engine

    settings = get_settings()
    assert settings.rls_enforce is True
    assert not embedded_pg.is_running(), "probe must exercise the externally supplied PostgreSQL URL"
    assert make_url(settings.database_url) == engine.url == make_url(os.environ["DATABASE_URL"])
    assert async_session_factory.kw["bind"] is engine
    assert settings.database_sync_url == os.environ["DATABASE_SYNC_URL"]
    assert _resolve_data_dir().resolve() == private_home / ".openestimate"
    assert _resolve_state_dir().resolve() == Path.cwd().resolve()
    app = main.create_app()
    startup = next(handler for handler in app.router.on_startup if handler.__name__ == "startup")
    emitted = []
    original_emit = main._emit_server_fail

    def record_failure(error):
        emitted.append(error)
        original_emit(error)

    main._emit_server_fail = record_failure
    try:
        for provisioning_fails in (False, True):
            calls = []
            expected = rls_setup.RLSConfigurationError("private role preflight injected refusal")

            async def provision(*_args):
                calls.append("provision")
                if provisioning_fails:
                    raise RuntimeError("private provision injected failure")
                return {"tables": 0, "roles": 0}

            async def verify(*_args):
                calls.append("verify")
                raise expected

            rls_setup.provision_rls = provision
            rls_setup.verify_rls_role = verify
            try:
                await asyncio.wait_for(startup(), timeout=90)
            except rls_setup.RLSConfigurationError as exc:
                assert exc is expected
            else:
                raise AssertionError("startup swallowed the RLS configuration error")
            assert calls == ["provision", "verify"]
            assert emitted[-1] is expected
        assert len(emitted) == 2
        print("RLS_STARTUP_PROPAGATION_OK cases=2")
    finally:
        await engine.dispose()
        current = asyncio.current_task()
        remaining = [task for task in asyncio.all_tasks() if task is not current]
        for task in remaining:
            task.cancel()
        await asyncio.gather(*remaining, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(run())
