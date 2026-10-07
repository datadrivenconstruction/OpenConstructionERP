# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Import-only RLS failure probe: private process, no database connections."""

import importlib.abc
import os
import socket
import sys
from pathlib import Path


def run():
    private_home = Path(os.environ["OE_DATA_DIR"]) / "test-home"
    private_home.mkdir()
    Path.home = classmethod(lambda cls: private_home)
    attempts = []

    def refuse_connection(*args, **kwargs):
        attempts.append("connection")
        raise AssertionError("Import-only probe attempted a database/network connection")

    import asyncpg
    import psycopg2

    asyncpg.connect = refuse_connection
    psycopg2.connect = refuse_connection
    socket.socket.connect = refuse_connection
    socket.socket.connect_ex = refuse_connection
    mode, enabled = sys.argv[1:]
    enabled = enabled == "true"
    injected = RuntimeError("injected RLS listener registration failure")
    settings_error = RuntimeError("injected unreadable RLS settings")

    if mode == "import":
        injected = ImportError("injected RLS module import failure")

        class RefuseRls(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "app.core.rls":
                    raise injected

        sys.meta_path.insert(0, RefuseRls())
    else:
        from app import config
        from app.core import rls

        def fail_settings():
            raise settings_error

        def fail_install(_session):
            if mode == "settings":
                # Engine construction already read settings successfully.
                config.get_settings = fail_settings
                sys.modules["app.database"].get_settings = fail_settings
            raise injected

        if mode != "success":
            rls.install = fail_install

    should_fail = mode == "settings" or (enabled and mode != "success")
    try:
        from app import database
    except Exception as error:
        assert should_fail, repr(error)
        assert error is (settings_error if mode == "settings" else injected), repr(error)
    else:
        try:
            assert not should_fail, "database import swallowed required RLS listener failure"
            assert database.async_session_factory.kw["bind"] is database.engine
        finally:
            # No connection was opened. Dispose the empty pool synchronously:
            # Windows asyncio otherwise creates a loopback socketpair itself.
            database.engine.sync_engine.dispose()
    assert attempts == [], attempts
    print("RLS_LISTENER_IMPORT_OK")


if __name__ == "__main__":
    run()
