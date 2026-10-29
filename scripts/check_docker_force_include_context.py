#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every force-include path the wheel needs must reach the Docker build context.

The backend wheel is built by pip inside the image, from ``./backend``, and
``[tool.hatch.build.targets.wheel.force-include]`` in backend/pyproject.toml
names paths that live outside the backend directory. hatchling resolves that
map while the wheel is being built and aborts the entire build on the first
entry it cannot find, with ``FileNotFoundError: Forced include not found``.
The Dockerfile therefore has to put every one of those paths into the image
before it installs, and there was nothing holding the two lists together.

What that cost. v16.2.0 published its PyPI package and its GitHub release and
shipped no container image at all. Two 16.2.0 commits added entries pointing
outside backend/: f5ae08469 added ``../data/match``, and 519a75ae5 added one
line per community pack. Neither reached the Dockerfile. data/ was copied, but
after the install, and packs/ was not copied at all, so the build died at
``pip install`` with ``/app/data/match`` missing. The release workflow is the
only thing that builds this image and it only triggers on tags, so the break
was invisible until the tag was already cut and PyPI had already published:
the worst ordering available, and not one anybody chose.

The shape of the defect is two lists in two files that have to agree with
nobody checking. That comes back the first time someone adds a pack, which is
a thing this project does routinely. Hence this check rather than a one-line
repair.

Direction matters, both ways
----------------------------
A map entry with no COPY is the failure above: the image does not build.

A COPY with no map entry is quieter and worse. Four packs in this repo are
deliberately held out of the community wheel, and out of these images with
it: ``aus-nzs`` (deprecated, superseded by ``aus`` and ``nzs``),
``batimatech-ca``, ``bimhessen-de`` and ``doker-formwork`` (regional and
industry packs not yet released). A COPY that
puts one of those into the build context bakes it into that image layer
permanently, because deleting a file in a later layer does not remove it from
the layer that added it, and these images go to ghcr.io publicly. Nothing
would fail. The image would build, pass its healthcheck and ship.

Those four are not written down here. Set equality against the map already
excludes them, and backend/tests/unit/test_community_packs_ship.py already
holds the map itself against the licence signals in the tree in both
directions. A second copy of that list in this file would be a second source
of truth, and it would be the one that goes stale on the day a pack correctly
becomes a community pack.

Why the Dockerfile lists packs one line at a time
------------------------------------------------
The licensing control above is the first reason. The second is that it has to
be that way regardless: app/core/partner_pack/discovery.py locates a pack by
globbing ``*/src/openconstructionerp_*/manifest.py`` under a ``packs``
directory beside the installed ``app`` package, so the per-pack ``src`` level
has to survive into the image with its shape intact. A single COPY with many
sources flattens them all into one destination directory, which would break
that glob for the packs that are supposed to ship. Both reasons point at the
same line-per-pack layout.

``../frontend/dist`` is exempt, and it is the only exemption
-----------------------------------------------------------
It cannot be copied. .dockerignore excludes ``frontend/dist`` and ``**/dist``,
so it is never present in the build context to copy from. It is satisfied
instead by the placeholder backend/hatch_build.py writes before hatchling
resolves the map, plus the ``mkdir`` in the unified stage, and the bytes that
actually get served are copied out of the frontend-build stage. The exemption
is a named constant rather than a silent filter so that adding a second one is
a visible act.

On the matching, which is the part that is easy to get wrong
-----------------------------------------------------------
The COPY directives are parsed, not searched for as substrings. A check that
grepped the Dockerfile for a pack name would be satisfied by this file's own
prose, or by a comment mentioning a pack, and would then be measuring the
comments rather than the build. Only the ``backend-base`` stage is read,
because that is the shared base both installs derive from; ``COPY --from=``
lines are skipped, since they copy between stages rather than from the
context; and ``backend/`` itself is excluded as the stage's own base copy,
which is what makes the map's backend-relative entries resolve.

Run ``--selftest`` to see it fail in both directions. That works on temporary
copies of the two real files and never writes to either.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(REPO, "backend", "pyproject.toml")
DOCKERFILE = os.path.join(REPO, "deploy", "docker", "Dockerfile.unified")

# The stage both pip installs derive from. Paths copied here are present for
# the api target and the unified target alike, which is why the fix belongs in
# it rather than in either one.
BASE_STAGE = "backend-base"

# Copied by the stage itself to make the wheel buildable at all. Every
# force-include entry that does NOT start with ``../`` resolves inside it.
STAGE_BASE_COPY = "backend"

# Satisfied without a COPY, and unable to have one. See the module docstring.
EXEMPT_FROM_COPY = frozenset({"../frontend/dist"})

_FROM = re.compile(r"^\s*FROM\s+.*?(?:\s+AS\s+(?P<name>\S+))?\s*$", re.IGNORECASE)
_COPY = re.compile(r"^\s*COPY\s+(?P<rest>.*)$", re.IGNORECASE)


def force_include_map(pyproject_path: str) -> dict[str, str]:
    """Return the wheel target's force-include map, source to destination."""
    with open(pyproject_path, "rb") as handle:
        data = tomllib.load(handle)
    targets = data["tool"]["hatch"]["build"]["targets"]
    return targets["wheel"]["force-include"]


def required_context_paths(pyproject_path: str) -> set[str]:
    """Return repo-root-relative paths the build context must carry.

    Every map entry starting with ``../`` points outside the backend directory
    and so outside what ``COPY backend/ backend/`` provides. The map writes
    them relative to backend/, one level below the context root, so dropping
    the prefix is what converts them into context paths.
    """
    outside = {key for key in force_include_map(pyproject_path) if key.startswith("../")}
    return {key[len("../") :] for key in outside - EXEMPT_FROM_COPY}


def _directives(dockerfile_path: str) -> list[str]:
    """Return the Dockerfile's logical lines, with continuations joined."""
    with open(dockerfile_path, encoding="utf-8") as handle:
        raw = handle.read()
    # Join backslash continuations first so a directive split over several
    # physical lines is read as the one instruction it is. Without this a
    # continued COPY would have its tail parsed as a separate line and its
    # sources silently dropped.
    joined = re.sub(r"\\\s*\n\s*", " ", raw)
    lines = []
    for line in joined.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return lines


def copied_context_paths(dockerfile_path: str, stage: str = BASE_STAGE) -> set[str]:
    """Return the context paths ``stage`` copies in, excluding its base copy.

    Only sources are collected, never the destination, and only from the named
    stage. ``COPY --from=`` is skipped: it reads from another build stage, not
    from the context, so it can never satisfy a force-include entry.
    """
    paths: set[str] = set()
    in_stage = False
    for line in _directives(dockerfile_path):
        from_match = _FROM.match(line)
        if from_match:
            in_stage = from_match.group("name") == stage
            continue
        if not in_stage:
            continue
        copy_match = _COPY.match(line)
        if not copy_match:
            continue
        tokens = copy_match.group("rest").split()
        if any(token.startswith("--from=") for token in tokens):
            continue
        operands = [token for token in tokens if not token.startswith("--")]
        # The last operand is the destination; everything before it is a source.
        for source in operands[:-1]:
            normalised = source.strip('"').rstrip("/")
            if normalised and normalised != STAGE_BASE_COPY:
                paths.add(normalised)
    return paths


def check(pyproject_path: str = PYPROJECT, dockerfile_path: str = DOCKERFILE) -> list[str]:
    """Return one line per disagreement between the two files, or an empty list."""
    required = required_context_paths(pyproject_path)
    copied = copied_context_paths(dockerfile_path)
    problems = []
    for path in sorted(required - copied):
        problems.append(
            f"{path} is force-included by the wheel but never copied into the build context. "
            f"The image will not build: pip aborts with 'Forced include not found'."
        )
    for path in sorted(copied - required):
        problems.append(
            f"{path} is copied into the build context but nothing in the wheel's force-include map "
            f"asks for it. If it is a pack held back from the community wheel, this ships it publicly."
        )
    for path in sorted(required):
        if not os.path.exists(os.path.join(REPO, path.replace("/", os.sep))):
            problems.append(f"{path} is force-included and copied, but no such path exists in the tree.")
    return problems


def _fixture(tmp: str, pyproject_edit=None, dockerfile_edit=None) -> tuple[str, str]:
    """Copy both real files into ``tmp``, optionally rewriting their text."""
    pyproject_copy = os.path.join(tmp, "pyproject.toml")
    dockerfile_copy = os.path.join(tmp, "Dockerfile.unified")
    shutil.copyfile(PYPROJECT, pyproject_copy)
    shutil.copyfile(DOCKERFILE, dockerfile_copy)
    for path, edit in (
        (pyproject_copy, pyproject_edit),
        (dockerfile_copy, dockerfile_edit),
    ):
        if edit is None:
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(edit(text))
    return pyproject_copy, dockerfile_copy


def _map_line_adder(slug: str):
    """Return an edit that adds ``slug`` to the map, after the last pack in it."""

    def edit(text: str) -> str:
        lines = text.splitlines(keepends=True)
        last = max(index for index, line in enumerate(lines) if line.startswith('"../packs/'))
        lines.insert(last + 1, f'"../packs/{slug}/src" = "packs/{slug}/src"\n')
        return "".join(lines)

    return edit


# A pack that really is in the tree and really is absent from the map, so
# adding it to one file at a time isolates one direction at a time without
# also tripping the does-it-exist rule.
HELD_BACK = "aus-nzs"


def _line_adder(line: str):
    """Return an edit that inserts ``line`` into the base stage."""
    anchor = "COPY backend/ backend/\n"

    def edit(text: str) -> str:
        return text.replace(anchor, anchor + line + "\n", 1)

    return edit


def selftest() -> int:
    """Prove the check goes red in both directions, on copies of the real files."""
    with tempfile.TemporaryDirectory() as tmp:
        pyproject, dockerfile = _fixture(tmp)
        if check(pyproject, dockerfile):
            print("selftest FAILED: the two files disagree before anything was changed")
            return 1

        # Direction one: the map gains a pack and the Dockerfile does not.
        # This is v16.2.0 exactly, and the image would not build.
        pyproject, dockerfile = _fixture(tmp, pyproject_edit=_map_line_adder(HELD_BACK))
        found = check(pyproject, dockerfile)
        if len(found) != 1 or HELD_BACK not in found[0] or "never copied" not in found[0]:
            print(
                "selftest FAILED: a map entry with no COPY was not reported, got:",
                found,
            )
            return 1

        # Direction two: the Dockerfile copies a pack the map does not name.
        # The image builds, and ships a pack that is held back on purpose.
        pyproject, dockerfile = _fixture(
            tmp,
            dockerfile_edit=_line_adder(f"COPY packs/{HELD_BACK}/src/ packs/{HELD_BACK}/src/"),
        )
        found = check(pyproject, dockerfile)
        if len(found) != 1 or HELD_BACK not in found[0] or "ships it publicly" not in found[0]:
            print(
                "selftest FAILED: a COPY with no map entry was not reported, got:",
                found,
            )
            return 1

        # Agreeing with each other is not enough on its own: a pair that names
        # a path nobody has committed still fails the build.
        pyproject, dockerfile = _fixture(
            tmp,
            pyproject_edit=_map_line_adder("selftest-absent"),
            dockerfile_edit=_line_adder("COPY packs/selftest-absent/src/ packs/selftest-absent/src/"),
        )
        found = check(pyproject, dockerfile)
        if len(found) != 1 or "no such path exists" not in found[0]:
            print(
                "selftest FAILED: an agreed pair naming a path not in the tree was accepted, got:",
                found,
            )
            return 1

        # A comment naming a pack must not satisfy the check, which is the
        # whole reason the COPY directives are parsed rather than grepped.
        pyproject, dockerfile = _fixture(
            tmp,
            pyproject_edit=_map_line_adder(HELD_BACK),
            dockerfile_edit=_line_adder(f"# packs/{HELD_BACK}/src is mentioned here and nowhere else"),
        )
        if not check(pyproject, dockerfile):
            print("selftest FAILED: a comment naming the path was accepted as a copy")
            return 1

        # A COPY --from= reads another stage, not the context, so it cannot
        # satisfy an entry either.
        pyproject, dockerfile = _fixture(
            tmp,
            pyproject_edit=_map_line_adder(HELD_BACK),
            dockerfile_edit=_line_adder(f"COPY --from=frontend-build packs/{HELD_BACK}/src/ packs/{HELD_BACK}/src/"),
        )
        if not check(pyproject, dockerfile):
            print("selftest FAILED: a COPY --from= was accepted as a copy from the build context")
            return 1

        # A COPY in another stage must not satisfy an entry either: the api
        # stage and the unified stage both install, so a path that only one of
        # them carries is missing for the other.
        pyproject, dockerfile = _fixture(
            tmp,
            pyproject_edit=_map_line_adder(HELD_BACK),
            dockerfile_edit=lambda text: text.replace(
                "# Data catalogs (for seed/enrichment).\n",
                f"COPY packs/{HELD_BACK}/src/ packs/{HELD_BACK}/src/\n# Data catalogs (for seed/enrichment).\n",
                1,
            ),
        )
        if not check(pyproject, dockerfile):
            print("selftest FAILED: a COPY in a later stage was accepted for the shared base stage")
            return 1

    print(
        "selftest ok: reports a force-include entry with no COPY, reports a COPY of a held-back "
        "pack with no entry, refuses a comment and a COPY --from= as substitutes, and stays quiet "
        "on the files as they are"
    )
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    required = required_context_paths(PYPROJECT)
    copied = copied_context_paths(DOCKERFILE)
    problems = check()
    if not problems:
        print(
            f"All {len(required)} force-include paths outside backend/ are copied into the "
            f"{BASE_STAGE} stage, and it copies nothing else.\n"
            f"Exempt by design, satisfied without a COPY: {', '.join(sorted(EXEMPT_FROM_COPY))}."
        )
        return 0
    print(f"The wheel's force-include map and {os.path.basename(DOCKERFILE)} disagree:\n")
    for line in problems:
        print("  " + line)
    print(
        f"\nforce-include, outside backend/ and not exempt ({len(required)}):\n"
        f"  {', '.join(sorted(required))}\n"
        f"copied into the {BASE_STAGE} stage ({len(copied)}):\n"
        f"  {', '.join(sorted(copied))}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
