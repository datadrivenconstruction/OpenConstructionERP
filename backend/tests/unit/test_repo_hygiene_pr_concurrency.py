# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PR hygiene runs may supersede only runs for the same PR."""

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/repo-hygiene.yml"


def _document():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _policy(event, ref, run_id):
    # Deliberately restricted interpreter for this documented GitHub &&/|| form.
    # Match the actual workflow expression so event cases cannot drift from YAML.
    policy = _document()["concurrency"]
    match = re.fullmatch(
        r"repo-hygiene-\$\{\{ github.event_name == '([^']+)' && github\.(ref) \|\| github\.(run_id) \}\}",
        policy["group"],
    )
    assert match, "group must use PR merge ref, with a unique non-PR run fallback"
    cancel = re.fullmatch(r"\$\{\{ github.event_name == '([^']+)' \}\}", policy["cancel-in-progress"])
    assert cancel, "cancellation must be event-scoped"
    context = {"ref": ref, "run_id": str(run_id)}
    suffix = (event == match[1] and context[match[2]]) or context[match[3]]
    return "repo-hygiene-" + suffix, event == cancel[1]


def test_existing_push_and_pr_triggers_and_required_job_names_remain():
    document = _document()
    # PyYAML YAML 1.1 reads the key 'on' as True.
    assert document.get("on", document.get(True)) == {"push": None, "pull_request": None}
    assert {job["name"] for job in document["jobs"].values()} == {
        "Whole-tree structural guards",
        "Commit history guards",
        "Locale and i18n guards",
    }


def test_new_commit_of_same_pr_supersedes_old_merge_ref_run():
    first = _policy("pull_request", "refs/pull/502/merge", 100)
    second = _policy("pull_request", "refs/pull/502/merge", 101)
    assert first == second == ("repo-hygiene-refs/pull/502/merge", True)


def test_distinct_prs_including_forks_cannot_cancel_each_other():
    # Fork branches can share names; repository PR merge refs remain distinct.
    assert (
        _policy("pull_request", "refs/pull/502/merge", 100)[0] != _policy("pull_request", "refs/pull/506/merge", 101)[0]
    )


@pytest.mark.parametrize(
    "ref", ["refs/heads/main", "refs/heads/feature/test", "refs/heads/release/18", "refs/tags/v18.4.0"]
)
def test_every_push_keeps_its_own_group_without_cancellation(ref):
    assert _policy("push", ref, 100) == ("repo-hygiene-100", False)
    assert _policy("push", ref, 101) == ("repo-hygiene-101", False)


def test_push_cannot_cancel_pr_for_same_branch():
    assert _policy("push", "refs/heads/feature/test", 100)[0] != _policy("pull_request", "refs/pull/502/merge", 101)[0]
