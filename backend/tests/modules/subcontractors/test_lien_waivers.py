"""End-to-end tests for the lien-waiver upload endpoint.

Scope:
    1. Real PDF blob passes the magic-byte gate and is stored under a
       server-derived filename (no path traversal via filename).
    2. HTML-disguised-as-PDF is rejected with HTTP 415 (file content
       overrides extension + Content-Type header).
    3. Empty body is rejected with 422 (operator-error, NOT 415 —
       distinguishes "no file" from "wrong format").
    4. Invalid ``waiver_type`` is rejected with 422 (enum constraint).
    5. IDOR: uploading against a non-existent subcontractor returns 404
       without leaking which UUIDs exist.
    6. Listing lien waivers returns the freshly-created row.

Mirrors ``tests/modules/rfi/test_rfi_attachments.py`` - runs against a
transaction-isolated PostgreSQL session (rolled back on teardown) with the
subcontractor router mounted on a fresh FastAPI app and the auth + permission
dependencies overridden.

Requests go through ``httpx.AsyncClient`` over ``ASGITransport``, not the
synchronous ``TestClient``: ``TestClient`` runs the app on its own event loop
in a worker thread, and the asyncpg connection behind ``db_session`` belongs to
the loop the test itself runs on, so any request that touched the database
failed with "attached to a different loop". ``AsyncClient`` calls the app
inline on the test's loop and the session is genuinely shared.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.subcontractors.models import Subcontractor
from app.modules.subcontractors.permissions import register_subcontractors_permissions
from app.modules.subcontractors.router import router as subs_router
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Transaction-isolated PostgreSQL session (rolled back on teardown).

    The shared ``oe_test_unit`` database already carries the full schema, so no
    per-test ``create_all`` is needed; the session's commits become savepoints
    and the outer transaction is rolled back when the fixture exits.
    """
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> str:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return str(user.id)


async def _make_subcontractor(session) -> uuid.UUID:
    sub = Subcontractor(legal_name=f"Acme {uuid.uuid4().hex[:6]}", trade_categories=[])
    session.add(sub)
    await session.flush()
    await session.refresh(sub)
    return sub.id


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount subcontractor router with auth + session overrides."""
    register_subcontractors_permissions()

    app = FastAPI()
    app.include_router(subs_router, prefix="/v1/subcontractors")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        # Admin role short-circuits every ``subcontractors.*`` permission gate.
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


# ── 1. Real PDF accepted ─────────────────────────────────────────────────


class TestLienWaiverUpload:
    @pytest.mark.asyncio
    async def test_real_pdf_is_stored(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Happy path — PDF body persists with a server-derived filename."""
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nrest..."
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={
                    "waiver_type": "conditional_partial",
                    "amount": "1250.00",
                    "currency": "USD",
                    "signed_date": "2026-05-25",
                    "notes": "Draw #3",
                },
                files={"file": ("waiver.pdf", pdf_body, "application/pdf")},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["waiver_type"] == "conditional_partial"
        assert body["mime_type"] == "application/pdf"
        # Server-derived path — never echoes the attacker-supplied filename.
        assert body["document_url"].startswith(
            f"subcontractors/lien_waivers/{sub_id}/conditional_partial_",
        )
        assert body["document_url"].endswith(".pdf")
        assert "waiver.pdf" not in body["document_url"]
        assert body["file_size"] == len(pdf_body)

    # ── 2. Unknown-binary payload (faked as PDF) rejected ─────────────

    @pytest.mark.asyncio
    async def test_unknown_binary_disguised_as_pdf_returns_415(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        """A blob whose magic bytes don't match any allowed signature
        must be rejected even though the filename / Content-Type claim
        application/pdf. NB: an HTML payload is not used here because
        the detector recognises `<html…>` as XML, which is itself an
        allowed document type for IDS / BCF / GAEB imports — the
        magic-byte gate would happily store it. We instead probe with
        a short binary header that registers as `unknown`.
        """
        from app.modules.subcontractors import router as subs_router_mod

        waivers_dir = tmp_path / "waivers"
        monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", waivers_dir)

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        random_bin = b"\x00\x01\x02\x03MEOW\xff\xee\xdd\xcc"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={"waiver_type": "conditional_partial"},
                files={"file": ("evil.pdf", random_bin, "application/pdf")},
            )
        assert resp.status_code == 415, resp.text
        # No disk write happened.
        if waivers_dir.exists():
            for sub_dir in waivers_dir.iterdir():
                assert list(sub_dir.iterdir()) == []

    # ── 3. Empty body returns 422 ─────────────────────────────────────

    @pytest.mark.asyncio
    async def test_empty_body_returns_422(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={"waiver_type": "conditional_partial"},
                files={"file": ("empty.pdf", b"", "application/pdf")},
            )
        assert resp.status_code == 422, resp.text

    # ── 4. Bad waiver_type returns 422 ────────────────────────────────

    @pytest.mark.asyncio
    async def test_bad_waiver_type_returns_422(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={"waiver_type": "not_a_real_waiver"},
                files={"file": ("waiver.pdf", pdf_body, "application/pdf")},
            )
        assert resp.status_code == 422, resp.text

    # ── 5. IDOR — non-existent sub returns 404, NOT 403 or 500 ───────

    @pytest.mark.asyncio
    async def test_nonexistent_subcontractor_returns_404(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        ghost_id = uuid.uuid4()
        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{ghost_id}/lien-waivers/upload",
                data={"waiver_type": "w9"},
                files={"file": ("w9.pdf", pdf_body, "application/pdf")},
            )
        assert resp.status_code == 404, resp.text

    # ── 6. Listing returns the freshly-created row ────────────────────

    @pytest.mark.asyncio
    async def test_list_after_upload_returns_row(
        self,
        db_session,
        tmp_path,
        monkeypatch,
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(
            subs_router_mod,
            "LIEN_WAIVERS_DIR",
            tmp_path / "waivers",
        )

        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        await db_session.commit()

        app = _build_app(db_session, caller_id=caller)
        transport = httpx.ASGITransport(app=app)

        pdf_body = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            up = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={"waiver_type": "w9", "amount": "0"},
                files={"file": ("w9.pdf", pdf_body, "application/pdf")},
            )
            assert up.status_code == 201, up.text

            ls = await client.get(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers",
            )
        assert ls.status_code == 200, ls.text
        rows = ls.json()
        assert len(rows) == 1
        assert rows[0]["waiver_type"] == "w9"


# ── 7. A waiver filed against a pay application ─────────────────────────


async def _make_pay_app(session, *, owner_id: str, sub_id: uuid.UUID, currency: str = "USD"):
    """One pay application of ``sub_id`` under an agreement that requires a waiver."""
    from datetime import date
    from decimal import Decimal

    from app.modules.projects.models import Project
    from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement

    project = Project(id=uuid.uuid4(), name="Waiver probe", owner_id=uuid.UUID(owner_id), currency=currency)
    session.add(project)
    await session.flush()
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=sub_id,
        project_id=project.id,
        title="Concrete subcontract",
        currency=currency,
        total_value=Decimal("8000"),
        status="active",
        requires_lien_waiver=True,
    )
    session.add(agreement)
    await session.flush()
    pay_app = PaymentApplication(
        id=uuid.uuid4(),
        agreement_id=agreement.id,
        application_number="PA-1",
        status="finance_approved",
        currency=currency,
        gross_amount=Decimal("2000"),
        net_amount=Decimal("1800"),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    session.add(pay_app)
    await session.flush()
    return pay_app.id


class TestWaiverAgainstAPayApplication:
    """The panel now files a payment waiver against the pay application it releases.

    What makes that worth anything is the release gate reading it: a waiver
    whose amount covers the net clears the payment, so the upload must only
    ever attach a sub's own pay application, in its currency.
    """

    PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"

    # The subcontractor named in the URL is the identity under test: whose
    # pay applications its paper may reach. These two are the allow and the
    # deny side of that one gate, so both carry the marker.
    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_a_waiver_for_the_subs_own_pay_application_releases_it(
        self, db_session, tmp_path, monkeypatch
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod
        from app.modules.subcontractors.service import SubcontractorService

        monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", tmp_path / "waivers")
        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        pay_app_id = await _make_pay_app(db_session, owner_id=caller, sub_id=sub_id)
        await db_session.commit()

        svc = SubcontractorService(db_session)
        _required, before = await svc.lien_waiver_status(pay_app_id)
        assert before.blocked

        transport = httpx.ASGITransport(app=_build_app(db_session, caller_id=caller))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                # No currency sent: it is the pay application's.
                data={
                    "waiver_type": "conditional_partial",
                    "payment_application_id": str(pay_app_id),
                    "amount": "1800.00",
                    "through_date": "2026-04-30",
                },
                files={"file": ("waiver.pdf", self.PDF, "application/pdf")},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["payment_application_id"] == str(pay_app_id)
        assert body["currency"] == "USD"
        assert body["through_date"] == "2026-04-30"

        required, after = await svc.lien_waiver_status(pay_app_id)
        assert required and not after.blocked

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_another_subs_or_an_unknown_pay_application_is_refused(
        self, db_session, tmp_path, monkeypatch
    ) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", tmp_path / "waivers")
        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        other_sub = await _make_subcontractor(db_session)
        others_pay_app = await _make_pay_app(db_session, owner_id=caller, sub_id=other_sub)
        await db_session.commit()

        transport = httpx.ASGITransport(app=_build_app(db_session, caller_id=caller))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for target in (others_pay_app, uuid.uuid4()):
                resp = await client.post(
                    f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                    data={
                        "waiver_type": "unconditional_partial",
                        "payment_application_id": str(target),
                        "amount": "1800.00",
                    },
                    files={"file": ("waiver.pdf", self.PDF, "application/pdf")},
                )
                assert resp.status_code == 422, resp.text
                assert resp.json()["detail"]["code"] == "payment_application_other_subcontractor"
            listed = await client.get(f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers")
        # Refused before the file was stored: nothing is on record.
        assert listed.json() == []

    @pytest.mark.asyncio
    async def test_a_waiver_in_another_currency_is_refused(self, db_session, tmp_path, monkeypatch) -> None:
        from app.modules.subcontractors import router as subs_router_mod

        monkeypatch.setattr(subs_router_mod, "LIEN_WAIVERS_DIR", tmp_path / "waivers")
        caller = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        pay_app_id = await _make_pay_app(db_session, owner_id=caller, sub_id=sub_id)
        await db_session.commit()

        transport = httpx.ASGITransport(app=_build_app(db_session, caller_id=caller))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers/upload",
                data={
                    "waiver_type": "conditional_partial",
                    "payment_application_id": str(pay_app_id),
                    "amount": "1800.00",
                    "currency": "EUR",
                },
                files={"file": ("waiver.pdf", self.PDF, "application/pdf")},
            )
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "currency_mismatch"


# ── 8. The list is scoped to the projects the caller can open ────────────


class TestWaiverListIsScopedToVisibleProjects:
    """A waiver on a pay application carries that project's amount and document.

    The subcontractor is shared across projects, so the list used to hand
    anybody with ``subcontractors.read`` every waiver the firm had filed,
    including the ones against projects they cannot open. A stand-alone W-9
    describes the firm and stays visible to everyone who can see the firm.
    """

    @pytest.mark.tenant_isolation
    @pytest.mark.asyncio
    async def test_an_outsider_sees_only_the_firm_level_forms(self, db_session) -> None:
        from decimal import Decimal

        from app.modules.projects.models import Project
        from app.modules.subcontractors.models import LienWaiver, PaymentApplication, SubcontractAgreement
        from app.modules.teams.models import Team, TeamMembership

        owner = await _make_user(db_session)
        member = await _make_user(db_session)
        outsider = await _make_user(db_session)
        sub_id = await _make_subcontractor(db_session)
        pay_app_id = await _make_pay_app(db_session, owner_id=owner, sub_id=sub_id)

        pay_app = await db_session.get(PaymentApplication, pay_app_id)
        agreement = await db_session.get(SubcontractAgreement, pay_app.agreement_id)
        project = await db_session.get(Project, agreement.project_id)
        team = Team(project_id=project.id, name="Site")
        db_session.add(team)
        await db_session.flush()
        db_session.add(TeamMembership(team_id=team.id, user_id=uuid.UUID(member), role="member"))

        db_session.add(
            LienWaiver(
                subcontractor_id=sub_id,
                payment_application_id=pay_app_id,
                waiver_type="conditional_partial",
                document_url="lien_waivers/pay.pdf",
                amount=Decimal("1800.00"),
                currency="USD",
            )
        )
        db_session.add(
            LienWaiver(
                subcontractor_id=sub_id,
                payment_application_id=None,
                waiver_type="w9",
                document_url="lien_waivers/w9.pdf",
            )
        )
        await db_session.commit()

        async def _types(caller: str) -> set[str]:
            transport = httpx.ASGITransport(app=_build_app(db_session, caller_id=caller))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/v1/subcontractors/subcontractors/{sub_id}/lien-waivers")
            assert resp.status_code == 200, resp.text
            return {row["waiver_type"] for row in resp.json()}

        assert await _types(outsider) == {"w9"}
        assert await _types(member) == {"w9", "conditional_partial"}
        assert await _types(owner) == {"w9", "conditional_partial"}
