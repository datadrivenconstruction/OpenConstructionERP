# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Building the app must not take logging away from the process that hosts it.

``configure_logging`` used to call ``logging.basicConfig(force=True)``. The
``force`` flag removes and closes every handler already on the root logger,
so a desktop shell that kept its own log file, pytest's ``caplog`` capture, or
any handler a host process installed before importing us stopped receiving
records the moment the app was built. Nothing failed, the records just went
nowhere.

The fix configures only the console handler the app owns. These tests install
a foreign handler first and check that it is still attached, still open and
still receiving records after the app configured logging twice, while the
app's own console output keeps its format, its request-id tag and its level.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from app.main import _CONSOLE_HANDLER_NAME, configure_logging
from app.middleware.request_id import RequestIDLogFilter


class _ForeignHandler(logging.Handler):
    """Stands in for a handler the host installed before the app was built."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []
        self.closed = False

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def close(self) -> None:
        self.closed = True
        super().close()


def _settings(level: str = "INFO") -> SimpleNamespace:
    # configure_logging reads exactly these two fields.
    return SimpleNamespace(log_level=level, app_debug=True)


def _ours(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if h.get_name() == _CONSOLE_HANDLER_NAME]


@pytest.fixture
def root_logger() -> Iterator[logging.Logger]:
    """Hand out the root logger and put it back exactly as it was found."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_filters = list(root.filters)
    saved_level = root.level
    try:
        yield root
    finally:
        for handler in list(root.handlers):
            if handler not in saved_handlers:
                root.removeHandler(handler)
                if handler.get_name() == _CONSOLE_HANDLER_NAME:
                    handler.close()
        for handler in saved_handlers:
            if handler not in root.handlers:
                root.addHandler(handler)
        root.filters[:] = saved_filters
        root.setLevel(saved_level)


def test_a_handler_the_host_installed_survives_and_keeps_receiving(root_logger: logging.Logger) -> None:
    foreign = _ForeignHandler()
    root_logger.addHandler(foreign)

    # Twice, because the test suite and some embedders build the app more
    # than once per process.
    configure_logging(_settings())
    configure_logging(_settings())

    assert foreign in root_logger.handlers
    assert foreign.closed is False

    logging.getLogger("app.probe.foreign").warning("host still hears this")
    assert "host still hears this" in foreign.messages


def test_caplog_keeps_capturing_after_the_app_configures_logging(
    root_logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    configure_logging(_settings())

    with caplog.at_level(logging.WARNING):
        logging.getLogger("app.probe.caplog").warning("captured after configure")

    assert "captured after configure" in caplog.text


def test_the_console_handler_is_ours_alone_and_keeps_its_format(root_logger: logging.Logger) -> None:
    configure_logging(_settings())
    configure_logging(_settings())

    ours = _ours(root_logger)
    assert len(ours) == 1, "a repeat call must replace our handler, not stack a second one"
    console = ours[0]
    assert isinstance(console, logging.StreamHandler)
    assert console.formatter is not None
    assert console.formatter._fmt == "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
    assert any(isinstance(f, RequestIDLogFilter) for f in console.filters)
    # The root filter is added once, not once per call.
    assert sum(isinstance(f, RequestIDLogFilter) for f in root_logger.filters) == 1

    # A record from a child logger renders with the request-id slot filled,
    # which only works when the filter sits on the handler itself.
    buffer = io.StringIO()
    console.setStream(buffer)
    logging.getLogger("app.probe.format").warning("formatted line")
    line = buffer.getvalue()
    assert "WARNING [-] app.probe.format: formatted line" in line


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
def test_the_root_level_follows_the_setting(root_logger: logging.Logger, level: str) -> None:
    configure_logging(_settings(level))
    assert root_logger.level == getattr(logging, level)
