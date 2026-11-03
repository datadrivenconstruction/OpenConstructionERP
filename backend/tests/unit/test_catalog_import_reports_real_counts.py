"""A catalogue import that lands no row must fail, and success carries real counts."""

import pytest

from app.modules.catalog import router as catalog_router

HEADER = "resource_code,name,type,category,unit,price_avg,price_min,price_max,currency,usage_count\n"


class _Savepoint:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> None:
        self.log.append("begin")

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.log.append("rollback" if exc_type else "release")
        return False


class _Session:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.added: list[object] = []

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self.log)

    async def execute(self, _stmt) -> None:
        self.log.append("delete")

    async def flush(self) -> None:
        return None

    def add_all(self, items) -> None:
        self.added.extend(items)


def _serve(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(catalog_router, "_read_region_catalog_csv", lambda region, folder: (text.encode(), "local"))


@pytest.mark.asyncio
async def test_header_only_file_fails_and_rolls_the_region_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, HEADER)
    session = _Session()
    with pytest.raises(RuntimeError, match="no resource could be imported"):
        await catalog_router.import_region_catalog(session, "USA_USD")  # type: ignore[arg-type]
    assert session.log[-1] == "rollback"


@pytest.mark.asyncio
async def test_rows_without_codes_are_not_a_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, HEADER + ",No code,material,General,m,1,1,1,USD,0\n")
    with pytest.raises(RuntimeError):
        await catalog_router.import_region_catalog(_Session(), "USA_USD")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_success_reports_imported_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(
        monkeypatch,
        HEADER
        + "A1,Mason,labor,General,h,30,25,35,USD,3\n,No code,material,General,m,1,1,1,USD,0\nB2,Bad,material,General,m,x,1,1,USD,0\n",
    )
    session = _Session()
    result = await catalog_router.import_region_catalog(session, "USA_USD")  # type: ignore[arg-type]
    assert result["imported"] == 1
    assert result["skipped"] == 2
    assert session.log[-1] == "release"
    assert session.added[0].currency == "USD"
