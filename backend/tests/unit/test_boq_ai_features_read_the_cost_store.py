"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The BOQ editor's readiness gate stands for features that read the cost store.

`BOQEditorPage` gates three actions behind `vectorReady`, which it computes
from the `cost_items` vector count reported by `/v1/costs/vector/status/`.
That gate is CORRECT and this file exists to keep it correct.

It is worth stating why, because the opposite was reported and believed for
a while. The page also hosts element matching, which searches the
per-language `cwicr_*_v3` catalogue collections, so a reader who judges the
gate by what the page is about concludes it probes the wrong store. It does
not. Rate suggestion, classification and anomaly checking all reach
``app.core.vector.vector_search``, which queries ``COST_TABLE``. The gate
reads exactly the store its own three features search, and the setup modal a
user meets after restoring only a catalogue snapshot is telling the truth:
those three really are unavailable.

So the failure this pins is somebody "fixing" working code. Repoint one of
the three at the catalogue store, or repoint ``vector_search`` itself, and
the frontend gate silently stops matching what it gates - with no test
failing anywhere, because each half looks reasonable alone.

The frontend half is deliberately absent, and that is a gap rather than an
oversight. It would have to assert that `vectorReady` derives from the
`cost_items` probe and that the setup modal still appears when that count is
low even while catalogues are installed. Expressing it means either
extracting the gate from a 5,816-line component or rendering the whole
thing; `BOQEditorPage.test.tsx`, despite its name, renders nothing and only
exercises pure helpers. The cost was judged not worth what it would catch,
given that this file covers the more consequential direction.

On evidence, since the tests here are proved two different ways. The two
driven tests were proved red the ordinary way, by repointing
``vector_search`` at ``cwicr_en_v3``: both failed on the collection name and
the file restored clean. The two AST tests were not proved that way, because
doing so means editing a 5,816-line service other agents are working in, to
demonstrate something an injection into a shared file is a poor way to
demonstrate. They were proved by showing the predicate separates instead -
the counts are in each test's docstring. That is weaker than a red run for
the specific method and stronger than a red run for showing the predicate is
not vacuous, so it is stated rather than glossed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any

import pytest

from app.core import vector as vector_module
from app.modules.boq.service import BOQService

# The three actions `ensureVectorDB` gates in BOQEditorPage.tsx, named as the
# service methods that serve them.
GATED_METHODS = ["suggest_rate", "classify_position", "check_anomalies"]


class _RecordingClient:
    """Stands in for a Qdrant client and remembers which collection was asked."""

    def __init__(self) -> None:
        self.collections: list[str] = []

    def query_points(self, collection_name: str, **_kw: Any) -> Any:
        self.collections.append(collection_name)
        return type("R", (), {"points": []})()


@pytest.fixture
def qdrant_models_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``from qdrant_client.models import ...`` resolve, real or stubbed.

    ``qdrant-client`` ships in the optional ``[semantic-clients]`` extra and
    is absent from plenty of environments, this one included. Skipping when
    it is missing would leave the two assertions that actually drive the
    search silently absent from most runs, and a skip inside a green
    summary reads exactly like a pass.

    So the real module is used wherever it is installed, and only where it
    is not does a minimal stand-in get installed for the three names
    ``vector_search`` constructs. Those objects are only built and handed to
    the client, never inspected, so nothing under test depends on their
    behaviour - which is what makes substituting them honest here and would
    not make it honest for a test about filtering.
    """
    try:
        import qdrant_client.models  # noqa: F401
    except ModuleNotFoundError:
        import sys
        import types

        pkg = types.ModuleType("qdrant_client")
        models = types.ModuleType("qdrant_client.models")
        for name in ("FieldCondition", "Filter", "MatchValue"):
            setattr(models, name, type(name, (), {"__init__": lambda self, **kw: None}))
        pkg.models = models
        monkeypatch.setitem(sys.modules, "qdrant_client", pkg)
        monkeypatch.setitem(sys.modules, "qdrant_client.models", models)


def test_vector_search_queries_the_cost_collection(
    monkeypatch: pytest.MonkeyPatch, qdrant_models_available: None
) -> None:
    """The search the gated features use reads cost_items, and nothing else.

    Driven rather than read: the collection name is captured from an actual
    call, so renaming the constant while leaving a literal behind, or the
    reverse, still fails here.
    """
    client = _RecordingClient()
    monkeypatch.setattr(vector_module, "_backend", lambda: "qdrant")
    monkeypatch.setattr(vector_module, "_get_qdrant", lambda: client)

    vector_module.vector_search([0.0] * 8, None, 5)

    assert client.collections == [vector_module.COST_TABLE]
    assert vector_module.COST_TABLE == "cost_items"


def test_the_region_filter_does_not_move_the_collection(
    monkeypatch: pytest.MonkeyPatch, qdrant_models_available: None
) -> None:
    """A region argument narrows the filter, never the store.

    Guards the plausible-looking edit that routes a regional query at a
    regional catalogue collection, which is where the two stores would get
    confused if anywhere.
    """
    client = _RecordingClient()
    monkeypatch.setattr(vector_module, "_backend", lambda: "qdrant")
    monkeypatch.setattr(vector_module, "_get_qdrant", lambda: client)

    vector_module.vector_search([0.0] * 8, "DE_BERLIN", 5)

    assert client.collections == [vector_module.COST_TABLE]


def _called_names(func: Any) -> set[str]:
    """Every plain function name called in ``func``'s body, via the AST.

    Parsed rather than grepped: a mention inside a string or a comment is
    not a call, and this has to distinguish those to be worth having.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
        # `asyncio.to_thread(vector_search, ...)` passes the function by
        # reference, so the name appears as an argument rather than as the
        # callee. Both spellings count as reaching it.
        if isinstance(node, ast.Name):
            names.add(node.id)
    return names


@pytest.mark.parametrize("method_name", GATED_METHODS)
def test_each_gated_feature_reaches_vector_search(method_name: str) -> None:
    """Each of the three gated actions goes through the cost-store search.

    Together with the two tests above this is the whole claim: the features
    behind the gate reach ``vector_search``, and ``vector_search`` reads
    ``cost_items``. Repointing either half breaks one of these.

    Shown to discriminate rather than assumed to: ``_called_names`` was run
    over all 91 methods of ``BOQService`` and returns ``vector_search`` for
    exactly four of them - these three and ``search_cost_items``. A predicate
    that answered yes for all 91 would pass here while proving nothing.
    """
    method = getattr(BOQService, method_name)

    assert "vector_search" in _called_names(method), (
        f"BOQService.{method_name} is gated in the BOQ editor on the cost_items vector "
        "count, so it has to search cost_items. It no longer reaches vector_search. "
        "If that is deliberate, the frontend gate in BOQEditorPage.tsx has to move with it."
    )


@pytest.mark.parametrize("method_name", GATED_METHODS)
def test_no_gated_feature_reaches_the_catalogue_store(method_name: str) -> None:
    """None of the three searches the catalogue collections.

    The positive test above would still pass if a method searched BOTH
    stores, which is the shape a well-meaning "make matching work here too"
    edit would take. This is the half that notices.

    The name set was checked against code that really does reach the
    catalogue store instead of being chosen by eye: applied to the 62
    functions of ``ranker_qdrant`` and ``qdrant_adapter``, this predicate
    fires on 14, among them ``ranker_qdrant.rank`` - which is precisely what
    such an edit would end up calling. An assertion forbidding names that
    appear nowhere would be green forever.
    """
    called = _called_names(getattr(BOQService, method_name))
    catalogue_entry_points = {"search", "cwicr_search", "country_to_collection", "resolve_cwicr_target"}

    assert not (called & catalogue_entry_points), (
        f"BOQService.{method_name} now reaches {sorted(called & catalogue_entry_points)}, "
        "which is the CWICR catalogue store. The BOQ editor gates this method on the "
        "cost_items count, so a user with an indexed cost store and no catalogue would "
        "be told the feature is ready and get nothing."
    )
