# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Signing is decided by what the release carries, not by how the run ended.

v15.0.0 was published with no signature, no certificate, no SHA256SUMS and no
SBOM. Nothing in the signing workflow failed; nothing in it ran. Its first job
required ``github.event.workflow_run.conclusion == 'success'``, the Desktop
Release run that built the installers ended ``cancelled`` because the rpm
bundler was still going after hours, and a skipped first job skips the whole
graph behind it. The tag's installers were all there.

A conclusion is a fact about a run. Whether a manifest over a release would be
honest is a fact about the release, and the two come apart in both directions:
a green run can be short an asset when a bundler fails inside a
``fail-fast: false`` matrix, and a cancelled one can carry every installer that
matters. So the completeness question belongs to a job that reads the assets.

What this test can and cannot do, stated rather than left to be discovered: it
reads the configuration, not the runner. It cannot show that GitHub starts the
workflow, and it cannot execute the inventory against a real release. What it
can do is fail the day somebody puts a run conclusion back in front of the
signature, which is the regression that cost v15.0.0 its seven assets.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "release-signing.yml"
SBOM_WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "sbom-and-licenses.yml"

#: The formats Desktop Release produces, and whether the release has to carry
#: one before it is worth signing. The rpm is the odd one out on purpose:
#: desktop-release.yml builds it in a job of its own because it can run for
#: hours where the .deb takes seconds, and that job states its own absence is
#: survivable ("Fedora and openSUSE users have no package for this version").
#: Requiring it here would withhold the signature from four installers over a
#: fifth that is documented as optional, which is the trade v15.0.0 lost.
#:
#: The .msi left this set in 15.2.0, when Windows stopped shipping a second
#: installer for the same platform. It has to leave here in the same change: the
#: assertion below is an equality against what the workflow requires, so a
#: format listed here that nobody builds would fail every release.
REQUIRED_FORMATS = frozenset({"exe", "dmg", "deb", "AppImage"})
OPTIONAL_FORMATS = frozenset({"rpm"})


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.is_file(), f"the signing workflow is not at {WORKFLOW}"
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = loaded.get("jobs") or {}
    print(f"\nread {WORKFLOW.name}: {len(jobs)} jobs {sorted(jobs)}")
    assert len(jobs) >= 4, (
        f"the workflow declares {len(jobs)} jobs. It is expected to resolve the tag, take an "
        f"inventory, build an SBOM, sign and confirm, so a number this small means the file "
        f"changed shape and every assertion below is reading something else."
    )
    return loaded


def job(workflow: dict, name: str) -> dict:
    jobs = workflow["jobs"]
    assert name in jobs, f"no job named {name!r}; the workflow declares {sorted(jobs)}"
    return jobs[name]


def inventory_job_name(workflow: dict) -> str:
    """Find the job that judges the installers, by what it does.

    Located by behaviour rather than by name so a rename is not a failure while
    deleting the reading is. Two jobs read the release's assets and both build a
    list of what is missing, so they need a discriminator: the confirmation
    judges the *manifest* and downloads SHA256SUMS to do it, the inventory
    judges the *installers* and never touches the manifest. Without this the
    match falls out of job ordering, which is not a property of anything.
    """
    matches = [
        name
        for name, spec in workflow["jobs"].items()
        for script in ["\n".join(step.get("run") or "" for step in spec.get("steps") or [])]
        if "gh release view" in script and "missing" in script and "SHA256SUMS" not in script
    ]
    assert len(matches) == 1, (
        f"expected exactly one job to judge the release's installers, found {matches}. Zero means "
        f"the only thing left to gate signing on is the run's conclusion, which is what left "
        f"v15.0.0 unsigned; more than one means this test is picking between them by luck."
    )
    return matches[0]


# ── The trigger ──────────────────────────────────────────────────────────────


def test_no_job_gates_on_the_desktop_release_run_conclusion(workflow: dict) -> None:
    """The exact regression. A run's conclusion must not decide the signature."""
    offenders = {name: spec["if"] for name, spec in workflow["jobs"].items() if "conclusion" in str(spec.get("if", ""))}
    assert not offenders, (
        f"these jobs gate on the triggering run's conclusion: {offenders}. A cancelled or failed "
        f"Desktop Release can still have published every installer, and a successful one can be "
        f"short an asset, so the conclusion decides nothing about whether the release is worth "
        f"signing. Read the assets off the release instead."
    )


def test_a_branch_dispatch_still_cannot_reach_the_signing_graph(workflow: dict) -> None:
    """The half of the old condition that was right, and has to survive.

    Desktop Release also runs from workflow_dispatch against a branch, where
    head_branch is a branch name and there is no release behind it at all.
    """
    condition = str(job(workflow, "resolve").get("if", ""))
    assert "head_branch" in condition and "'v'" in condition, (
        f"the resolve job no longer restricts workflow_run events to tag runs: {condition!r}. "
        f"Dropping the conclusion test was the fix; dropping this one sends the workflow after "
        f"a release that does not exist."
    )


# ── The replacement ──────────────────────────────────────────────────────────


def test_signing_waits_on_the_inventory(workflow: dict) -> None:
    inventory = inventory_job_name(workflow)
    sign = job(workflow, "sign")

    assert inventory in (sign.get("needs") or []), (
        f"the sign job needs {sign.get('needs')} and not {inventory!r}, so it can sign a release nothing has looked at."
    )
    condition = str(sign.get("if", ""))
    assert f"needs.{inventory}.result" in condition, (
        f"sign depends on {inventory!r} but does not read its result: {condition!r}. A `needs` "
        f"edge alone lets a failed inventory through on any `if` that is a status expression, "
        f"and this one is, because it has to survive the SBOM being skipped on a backfill."
    )
    assert "'success'" in condition, (
        f"sign does not require the inventory to have succeeded: {condition!r}. Spelling out the "
        f"states that are allowed is what keeps an unfinished inventory from reading as consent."
    )
    assert "'skipped'" in condition, (
        f"sign allows only a successful inventory: {condition!r}. A backfill skips the inventory "
        f"by its own `if`, and a condition that names success alone withholds the signature from "
        f"every backfill without saying so - the same shape of silent non-run this file exists to "
        f"prevent, arrived at from the other side."
    )


def test_the_inventory_requires_every_platform_and_not_the_rpm(workflow: dict) -> None:
    """Read the formats out of the check itself, not out of a comment.

    Each line that adds to ``missing`` names the file extensions that satisfy
    one platform. Collecting them from those lines is what separates a rule that
    is enforced from one that is merely described nearby.
    """
    name = inventory_job_name(workflow)
    script = "\n".join(step.get("run") or "" for step in workflow["jobs"][name]["steps"])

    required: set[str] = set()
    for line in script.splitlines():
        if "missing=" not in line or "grep" not in line:
            continue
        for pattern in re.findall(r"grep -qE '([^']+)'", line):
            required.update(re.findall(r"[A-Za-z][A-Za-z0-9]*", pattern))

    print(f"\n{name} requires an asset ending in: {sorted(required)}")
    assert required == set(REQUIRED_FORMATS), (
        f"the inventory requires {sorted(required)}, expected {sorted(REQUIRED_FORMATS)}. Every "
        f"platform Desktop Release builds has to be represented before a manifest over the "
        f"release can be honest, and nothing beyond that may block the signature."
    )
    assert not (required & OPTIONAL_FORMATS), (
        f"the inventory requires {sorted(required & OPTIONAL_FORMATS)}. desktop-release.yml "
        f"builds the rpm in a job of its own and treats a missing one as survivable; requiring "
        f"it here reproduces exactly what happened to v15.0.0, where an unfinished rpm cost the "
        f"release its signature, its checksums and its SBOM."
    )


def platform_patterns(workflow: dict, name: str, variable: str) -> set[str]:
    """Collect the asset suffixes one job accumulates into ``variable``."""
    script = "\n".join(step.get("run") or "" for step in workflow["jobs"][name]["steps"])
    found: set[str] = set()
    for line in script.splitlines():
        if f"{variable}=" not in line or "grep" not in line:
            continue
        for pattern in re.findall(r"grep -qE '([^']+)'", line):
            found.update(re.findall(r"[A-Za-z][A-Za-z0-9]*", pattern))
    return found


def test_the_confirmation_verifies_the_cause_it_reports(workflow: dict) -> None:
    """A red inventory is not evidence of *why* it was red.

    The inventory fails for two unrelated reasons: the release is short a
    platform, or the release could not be read at all. The confirmation used to
    treat the failure itself as proof of the first and told the reader to re-run
    Desktop Release, which for an API flake sends them to rebuild installers
    that were never missing. So it asks the platform question again off the
    asset list it already holds. That means the same suffixes are written twice,
    and two copies of a rule drift unless something compares them.
    """
    confirm_formats = platform_patterns(workflow, "confirm", "absent_platforms")
    assert confirm_formats, (
        "the confirmation no longer checks the platforms itself, so its 'that was the right "
        "outcome' message is back to inferring the cause from a neighbouring job's colour - "
        "which reports an unreadable release as a missing installer."
    )
    inventory_formats = platform_patterns(workflow, inventory_job_name(workflow), "missing")
    print(f"\nconfirm checks {sorted(confirm_formats)}; inventory checks {sorted(inventory_formats)}")
    assert confirm_formats == inventory_formats, (
        f"the confirmation checks {sorted(confirm_formats)} and the inventory "
        f"{sorted(inventory_formats)}. They answer the same question about the same release and "
        f"one of them decides whether to sign while the other decides what to tell the reader, so "
        f"a difference between them is a run that refuses for a reason it then misreports."
    )


def test_the_inventory_says_so_when_it_could_not_read_the_release(workflow: dict) -> None:
    """Not measuring a release and judging it are different outcomes.

    Both end the job red. Under ``set -e`` an unreadable release ends it red
    with no output whatsoever, which is the worst of the two: the only record
    left is the failure itself, and the failure is what the confirmation reads.
    """
    name = inventory_job_name(workflow)
    script = "\n".join(step.get("run") or "" for step in workflow["jobs"][name]["steps"])

    assert "gh release view" in script
    guarded = [line for line in script.splitlines() if "gh release view" in line and line.lstrip().startswith("if !")]
    assert guarded, (
        f"the {name!r} job calls `gh release view` without catching its failure, so a transient "
        f"API error kills the step where it stands and the run's only account of itself is a bare "
        f"red job. Capture it and say the release was not measured."
    )
    assert "not measured" in script, (
        f"the {name!r} job catches the read failure but does not distinguish it in what it prints. "
        f"'Could not read the release' and 'the release is short a platform' send the reader to "
        f"two different repairs."
    )


def test_the_confirmation_still_reports_when_nothing_was_signed(workflow: dict) -> None:
    """The job that looks at the release must outlive the job that signs it.

    It is the only reading in the workflow that can tell a signed release from
    an unsigned one, so it has to run when `sign` did not - which is the case it
    exists for.
    """
    confirm = job(workflow, "confirm")
    condition = str(confirm.get("if", ""))

    assert "always()" in condition, (
        f"the confirm job is no longer unconditional: {condition!r}. A confirmation that is "
        f"skipped alongside the failure it reports on tells nobody anything."
    )
    inventory = inventory_job_name(workflow)
    assert inventory in (confirm.get("needs") or []), (
        f"confirm does not need {inventory!r}, so it cannot tell a deliberate refusal (the "
        f"release is short a platform, and re-running Desktop Release is the repair) from a "
        f"wiring failure (the repair is in this workflow). One message for both is how the "
        f"first gets diagnosed as the second."
    )


# ── The manifest against the bytes ───────────────────────────────────────────


def confirm_script(workflow: dict) -> str:
    return "\n".join(step.get("run") or "" for step in job(workflow, "confirm")["steps"])


def test_the_confirmation_compares_hashes_and_not_only_names(workflow: dict) -> None:
    """Coverage and correctness are different questions about the same manifest.

    v17.0.2 was published with a ``SHA256SUMS`` that named all twelve of its
    assets and stated the wrong hash for two of them. Two runs of this workflow
    share one release on purpose, ``gh release upload --clobber`` replaces an
    asset in place, and the second run regenerated both SBOMs after the first
    run's manifest had been written and signed over them. The name survived and
    the bytes did not, so every check in this job passed while
    ``sha256sum -c SHA256SUMS`` would have failed for anyone downloading it.

    The window closed when the second manifest landed a minute later. A run
    that dies between those two uploads does not close it at all, and this job
    runs on ``always()``, so it would have reported a fully covered manifest
    and gone green over a release that was permanently wrong.
    """
    script = confirm_script(workflow)

    assert ".digest" in script, (
        "the confirmation no longer reads the digests GitHub reports for each asset, so it is "
        "back to asking only whether every asset is named in SHA256SUMS. A name survives an "
        "asset being replaced; the hash beside it does not."
    )
    assert "release serves" in script, (
        "the confirmation reads the digests but no longer reports the two hashes side by side. "
        "'The manifest is wrong' without the pair is a finding nobody can act on."
    )

    # The comparison skips an asset the manifest does not name, on the grounds
    # that the coverage check above has already refused for it. That is an
    # invariant about the order of two checks in one script, and it is the kind
    # that survives a reordering silently: the digest loop would go on
    # comparing what it could and report a clean count while a whole asset went
    # unmentioned by either half.
    assert script.index("does not cover:") < script.index("release serves"), (
        "the digest comparison now runs before the coverage refusal. It skips assets the manifest "
        "does not name because that refusal is supposed to have happened first, so in this order "
        "an uncovered asset is dropped by one check and never reached by the other."
    )


def test_the_confirmation_cannot_pass_by_comparing_nothing(workflow: dict) -> None:
    """A gate that measured nothing must not read like a gate that was satisfied.

    Every asset is compared through a digest GitHub reports, and an asset it
    reports no digest for cannot be compared at all. If that ever becomes all
    of them, the loop finds no mismatch and the obvious code path says so in
    exactly the words it uses when the manifest is correct.
    """
    script = confirm_script(workflow)

    assert '"$compared" -eq 0' in script, (
        "nothing in the confirmation refuses when it compared zero assets. An empty comparison "
        "produces no mismatch, and no mismatch is the same output as a manifest that checked out."
    )
    assert "Compared ${compared}" in script, (
        "the confirmation does not print how many entries it compared next to its verdict. The "
        "count is what separates 'every hash matches' from 'no hash was looked at'."
    )


# ── The SBOM the manifest is written over ────────────────────────────────────


@pytest.fixture(scope="module")
def sbom_workflow() -> dict:
    assert SBOM_WORKFLOW.is_file(), f"the SBOM workflow is not at {SBOM_WORKFLOW}"
    return yaml.safe_load(SBOM_WORKFLOW.read_text(encoding="utf-8"))


def test_the_sbom_pins_both_fields_that_vary_between_generations(sbom_workflow: dict) -> None:
    """Removing the race is better than narrowing it.

    Both generators stamp the moment they ran into the document, so the same
    tag inventoried twice produces two files that differ and the second one
    clobbers the first. Two fields carry the whole difference. The timestamp is
    the obvious one. ``serialNumber`` is the one that hides: it is a fresh UUID
    per generation, and two UUIDs are the same length, so the v17.0.2 pair were
    both 174222 bytes with the same 141 components and still hashed apart.

    Pinning the timestamp alone would leave the file irreproducible for a
    reason a byte count cannot show, which is why both are named here.
    """
    script = "\n".join(step.get("run") or "" for step in sbom_workflow["jobs"]["generate"]["steps"])

    for field in ("serialNumber", "metadata"):
        assert field in script, (
            f"nothing in the SBOM job pins {field!r}. A regenerated SBOM then differs from the "
            f"published one, and the second of the two runs per release clobbers an asset the "
            f"first run's SHA256SUMS was computed and signed over."
        )
    assert "timestamp" in script, (
        "nothing in the SBOM job pins the generation timestamp, which is the field that made "
        "v17.0.2's two SBOMs differ."
    )


def test_the_sbom_does_not_clobber_an_asset_it_would_not_change(sbom_workflow: dict) -> None:
    """``--clobber`` deletes before it uploads, so it is never free.

    It changes the asset id and there is a moment when the name resolves to
    nothing, which is what killed the dispatched run on v15.6.0. With the
    fields above pinned, the second run of a release regenerates a file
    identical to the published one, and replacing it buys that risk for no
    change at all.
    """
    script = "\n".join(step.get("run") or "" for step in sbom_workflow["jobs"]["generate"]["steps"])

    assert "not clobbering it" in script, (
        "the attach step uploads unconditionally again. Pinning the varying fields makes the "
        "second run's SBOM identical to the published one; re-uploading it anyway reintroduces "
        "the delete-then-upload window for a file whose bytes did not move."
    )
