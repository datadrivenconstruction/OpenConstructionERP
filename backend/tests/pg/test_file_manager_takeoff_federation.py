"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the file manager lists takeoff's own store alongside the documents area.

The takeoff module keeps its documents in ``oe_takeoff_document``. The
"open from project files" dialog listed ``oe_documents_document`` and nothing
else, so a plan open in the takeoff viewer could not be found by name in a
dialog that called itself "project files" - two stores, one label, and the
user told something false.

The fix federates on the server: ``list_project_files`` collects the takeoff
store as the ``takeoff`` kind, which is the discriminator the caller groups by.
These properties need a real cluster because they are all database-level - the
project scoping of two independent tables, the role lookup behind the module
permission, and the duplicate suppression that keeps a blob shared by both
stores from being counted twice.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.documents.models import Document
from app.modules.projects.file_manager_service import list_project_files
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument
from app.modules.users.models import User


async def _user(session, *, role: str = "editor") -> User:
    user = User(
        email=f"fm-fed-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session, owner: User, name: str) -> Project:
    project = Project(name=name, owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _document(session, project: Project, owner: User, name: str, *, path: str = "") -> Document:
    doc = Document(
        project_id=project.id,
        name=name,
        category="drawing",
        mime_type="application/pdf",
        file_path=path,
        uploaded_by=str(owner.id),
    )
    session.add(doc)
    await session.flush()
    return doc


async def _takeoff(
    session,
    project: Project,
    owner: User,
    filename: str,
    *,
    source_id: str | None = None,
    path: str = "",
) -> TakeoffDocument:
    doc = TakeoffDocument(
        filename=filename,
        pages=1,
        size_bytes=2048,
        project_id=project.id,
        owner_id=owner.id,
        source_document_id=source_id,
        file_path=path,
    )
    session.add(doc)
    await session.flush()
    return doc


def _names(listing, kind: str) -> set[str]:
    return {row.name for row in listing.items if row.kind == kind}


@pytest.mark.asyncio
async def test_the_listing_carries_both_stores_for_the_project(pg_session):
    """Both stores appear, each tagged with the module it came from.

    This is the reported bug in its smallest form: the takeoff-only sheet was
    invisible to a dialog that promised the project's files. It must now be
    there, and it must be distinguishable from a documents-area file, because
    the dialog names the group it puts each row in.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Federated listing")
    await _document(pg_session, project, owner, "Baugenehmigung.pdf")
    await _takeoff(pg_session, project, owner, "A-2.01 Grundriss Erdgeschoss.pdf")

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
    )

    assert _names(listing, "document") == {"Baugenehmigung.pdf"}
    assert _names(listing, "takeoff") == {"A-2.01 Grundriss Erdgeschoss.pdf"}
    # The envelope has to be able to say how much it is showing, or a picker
    # built on it cannot admit to being a slice.
    assert listing.total == len(listing.items) == 2


@pytest.mark.asyncio
async def test_searching_the_takeoff_only_sheet_by_name_finds_it(pg_session):
    """A free-text search hits the takeoff store, not just the documents area.

    The reported symptom was typing "Grundriss" and getting nothing while that
    exact sheet was open in the viewer. The search runs over every collected
    row before paging, so the answer does not depend on which page the row
    happens to land on.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Search across stores")
    await _document(pg_session, project, owner, "Baugenehmigung.pdf")
    await _takeoff(pg_session, project, owner, "A-2.01 Grundriss Erdgeschoss.pdf")

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
        query="grundriss",
    )

    assert [row.name for row in listing.items] == ["A-2.01 Grundriss Erdgeschoss.pdf"]
    assert listing.items[0].kind == "takeoff"
    assert listing.total == 1


@pytest.mark.asyncio
async def test_neither_store_leaks_rows_from_a_foreign_project(pg_session):
    """Project scoping holds on BOTH tables, not just the one already scoped.

    A new collector is a new way to cross a project boundary. The documents
    slice was already scoped; this pins that the takeoff slice is too, from the
    same call, so a regression in either one is caught here.
    """
    owner = await _user(pg_session)
    mine = await _project(pg_session, owner, "Mine")
    theirs = await _project(pg_session, owner, "Theirs")
    await _document(pg_session, mine, owner, "Mine document.pdf")
    await _takeoff(pg_session, mine, owner, "Mine takeoff.pdf")
    await _document(pg_session, theirs, owner, "Foreign document.pdf")
    await _takeoff(pg_session, theirs, owner, "Foreign takeoff.pdf")

    listing = await list_project_files(
        pg_session,
        str(mine.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
    )

    assert {row.name for row in listing.items} == {"Mine document.pdf", "Mine takeoff.pdf"}
    assert listing.total == 2


@pytest.mark.asyncio
async def test_a_role_without_takeoff_read_receives_no_takeoff_rows(pg_session):
    """The federation must not become a way around the module permission.

    ``takeoff.read`` requires VIEWER; the field roles rank below it and get 404
    from every takeoff endpoint. Such a caller must still get the project's
    documents - the assertion is 200-with-documents AND zero takeoff rows, not
    merely the absence of takeoff rows, because an endpoint that failed
    outright would satisfy the weaker half while breaking the page.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Module permission")
    await _document(pg_session, project, owner, "Baugenehmigung.pdf")
    await _takeoff(pg_session, project, owner, "A-2.01 Grundriss Erdgeschoss.pdf")

    field_worker = await _user(pg_session, role="field_worker")

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(field_worker.id),
        kinds=["document", "takeoff"],
    )

    assert _names(listing, "document") == {"Baugenehmigung.pdf"}
    assert _names(listing, "takeoff") == set()
    assert listing.total == 1

    # And the same project, read by a role that DOES hold takeoff.read, still
    # carries the takeoff row - otherwise this test would also pass with the
    # collector removed entirely.
    permitted = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
    )
    assert _names(permitted, "takeoff") == {"A-2.01 Grundriss Erdgeschoss.pdf"}


@pytest.mark.asyncio
async def test_a_file_open_in_both_stores_is_offered_once(pg_session):
    """A takeoff document made from a project file is not listed twice.

    Opening a project file in takeoff references the same blob and stamps
    ``source_document_id``. Both rows describe one file, so the listing keeps
    the document row and hands it the takeoff id, which lets a caller open the
    takeoff document that already exists instead of asking for a second one.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Same blob twice")
    source = await _document(pg_session, project, owner, "A-2.01 Grundriss Erdgeschoss.pdf")
    takeoff = await _takeoff(
        pg_session,
        project,
        owner,
        "A-2.01 Grundriss Erdgeschoss.pdf",
        source_id=str(source.id),
    )

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
    )

    assert listing.total == 1, "the same file was offered from both stores"
    row = listing.items[0]
    assert row.kind == "document"
    assert row.extra.get("takeoff_document_id") == str(takeoff.id)


@pytest.mark.asyncio
async def test_a_direct_upload_cross_linked_into_documents_is_offered_once(pg_session):
    """The other link direction: a takeoff upload that cross-linked a document.

    A direct takeoff upload writes a ``Document`` row pointing at the takeoff
    file path, so the two rows share a blob with no ``source_document_id``
    between them. Path equality is what catches this one; without it the file
    manager would start double-counting every takeoff upload ever made.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Cross-linked upload")
    shared_path = f"/tmp/takeoff-{uuid.uuid4().hex}.pdf"
    await _document(pg_session, project, owner, "Aufmass.pdf", path=shared_path)
    takeoff = await _takeoff(pg_session, project, owner, "Aufmass.pdf", path=shared_path)

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["document", "takeoff"],
    )

    assert listing.total == 1, "a cross-linked takeoff upload was counted twice"
    assert listing.items[0].kind == "document"
    assert listing.items[0].extra.get("takeoff_document_id") == str(takeoff.id)


@pytest.mark.asyncio
async def test_the_duplicate_is_suppressed_even_when_only_takeoff_is_asked_for(pg_session):
    """Filtering to one kind must not resurrect the duplicate.

    ``kinds=takeoff`` skips the documents collector, so nothing in the returned
    rows could reveal the duplication. If suppression depended on the document
    slice being present, the sidebar count and this filtered list would
    disagree about the same project.
    """
    owner = await _user(pg_session)
    project = await _project(pg_session, owner, "Filtered to takeoff")
    source = await _document(pg_session, project, owner, "A-2.01 Grundriss Erdgeschoss.pdf")
    await _takeoff(
        pg_session,
        project,
        owner,
        "A-2.01 Grundriss Erdgeschoss.pdf",
        source_id=str(source.id),
    )
    await _takeoff(pg_session, project, owner, "Handaufmass Treppenhaus.pdf")

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["takeoff"],
    )

    assert [row.name for row in listing.items] == ["Handaufmass Treppenhaus.pdf"]
    assert listing.total == 1


@pytest.mark.asyncio
async def test_the_takeoff_slice_is_project_scoped_not_owner_scoped(pg_session):
    """A colleague's sheet is part of the project's files.

    The takeoff module's own listing filters by ``owner_id``, but every other
    reader of a project-bound takeoff document authorises on the project. A
    picker that hid a colleague's sheet would misreport what the project holds,
    so this pins the wider - and already permitted - scope deliberately.
    """
    owner = await _user(pg_session)
    colleague = await _user(pg_session)
    project = await _project(pg_session, owner, "Two uploaders")
    await _takeoff(pg_session, project, colleague, "Kollegenaufmass.pdf")

    listing = await list_project_files(
        pg_session,
        str(project.id),
        user_id=str(owner.id),
        kinds=["takeoff"],
    )

    assert [row.name for row in listing.items] == ["Kollegenaufmass.pdf"]
