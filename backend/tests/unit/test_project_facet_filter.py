"""Phase and project-type filter used by the analytics overview (#567)."""

from types import SimpleNamespace

from app.modules.projects.facets import FACET_UNSET, filter_by_facets


def _p(phase, project_type):
    return SimpleNamespace(phase=phase, project_type=project_type)


PROJECTS = [_p("tender", "office"), _p("construction", "office"), _p(None, "housing"), _p(" ", None)]


def test_no_filter_keeps_every_project() -> None:
    assert filter_by_facets(PROJECTS, None, None) == PROJECTS
    assert filter_by_facets(PROJECTS, "all", "all") == PROJECTS


def test_phase_filter_matches_exactly() -> None:
    assert filter_by_facets(PROJECTS, "tender", None) == [PROJECTS[0]]


def test_unset_matches_blank_and_missing() -> None:
    assert filter_by_facets(PROJECTS, FACET_UNSET, None) == PROJECTS[2:]


def test_both_filters_combine() -> None:
    assert filter_by_facets(PROJECTS, "construction", "office") == [PROJECTS[1]]
    assert filter_by_facets(PROJECTS, "tender", "housing") == []
