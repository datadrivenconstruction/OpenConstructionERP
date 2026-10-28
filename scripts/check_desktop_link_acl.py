#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if the desktop application window cannot reach the commands it invokes.

The launcher serves the application from the backend it starts, and navigates
the webview to ``http://127.0.0.1:<port>/``. Tauri calls that a REMOTE origin:
``Webview::is_local_url`` counts only the Tauri custom protocol and a
``frontendDist`` that is a URL, and this build's ``frontendDist`` is a
directory. A remote origin then hits the branch in ``webview/mod.rs`` that
reads ``if (plugin_command.is_some() || has_app_acl_manifest || !is_local) &&
invoke.acl.is_none()`` and rejects the call.

That is not a hypothetical. Before the ``permissions`` directory and the
``app-window`` capability existed, the application declared no ACL of its own,
no capability named the loopback origin, and so every ``#[tauri::command]``
invoked from the application window was refused. The user-visible shape of it
was that every outbound link in the product - the docs, the repository, the
marketing site, contact mail - did nothing at all when clicked. No error, no
browser, nothing, because the frontend swallowed the rejection.

Four things have to stay true for that to stay fixed, and this gate checks all
four.

Everything the application page invokes has to be reachable from it
-------------------------------------------------------------------
A capability with a ``remote`` block has to exist, its URL patterns have to
actually cover the address the launcher navigates to, and the permissions it
names have to resolve to every command the page calls. Checking that the file
merely contains the string ``http://127.0.0.1:*`` would pass a file where
somebody renamed the permission and severed the grant, so the check resolves
the permission set for real and matches the pattern against sample addresses.

Each command is checked on its own, because a grant that covers one says
nothing about the rest and the failure looks identical from the outside: a
control that is on screen, is enabled, and does nothing when pressed.

Nothing else may go dead the same way
-------------------------------------
Declaring an application ACL at all flips ``has_app_acl_manifest`` true, which
turns on the same check for the LOCAL origin, where app commands used to be
unrestricted. So every command in ``generate_handler!`` now needs a grant from
some capability or it is dead on both origins with nothing on screen to say so.
Adding a command and forgetting its permission is a silent regression of
exactly the shape this file exists to close, so it fails here instead.

The capability files have to be the whole answer
------------------------------------------------
Tauri's ``dynamic-acl`` feature is in its own default feature list, so
``Manager::add_capability`` is compiled into this build without us asking for
it. A capability granted that way lasts for the life of the process and is
recorded in no file, so ``capabilities/`` would go on describing a narrower
application than the one that runs. What makes that worth a check rather than a
note is that the reassuring version of it - we do not call it - is exactly the
kind of statement that gets written down once and quietly stops being true.

Nothing may hand a link to something that re-parses it
------------------------------------------------------
Opening a link on Windows used to run ``cmd /c start "" "<target>"``, so the
address became part of a command line that cmd.exe re-parsed. Quoting held off
the separators, but cmd expands ``%NAME%`` inside double quotes as readily as
outside. Measured: ``%USERNAME%`` became the account name and ``%CD%`` became
the full path of the working directory, both sent to whatever host the link
named. It is now ``ShellExecuteW`` with the target as one argument.

This check is deliberately NOT "have the three helpers that used to do the
quoting come back". They are deleted, so the compiler already refuses calls to
them, but the compiler has nothing to say about a fresh ``Command::new("cmd")``
written under a fourth name, and a guard keyed to a helper stops protecting the
moment somebody adds a second caller. So the question asked here is a property
of the path instead: does anything in the Windows link-opening path construct a
process at all, and does anything anywhere in the crate start a program that
re-parses what it is given.

It reads the source rather than the call graph, so it cannot follow a process
construction into a helper the opener calls. What it can do, and does, is fail
when the set of opener functions it knows about stops matching what is in the
file, which is the moment its own scope has gone stale.

The pattern matcher below is a deliberately narrow subset of the URLPattern
standard that Tauri actually uses, so it self-tests before every scan against
cases measured against the real ``tauri_utils::acl::RemoteUrlPattern``. A
matcher that quietly stopped matching would make this gate vacuously green.

The same reasoning applies to every check here and is worth stating once. A
proof that plants a defect has to check the defect actually landed, or its
silence is indistinguishable from its success. The proof for the opener change
first reported "found 0 sites to plant" because ``main.rs`` is a CRLF file and
the planted literals were not; had it asserted only that the tests went red it
would have said nothing while looking like it ran. Every scan below therefore
asserts on what it found before drawing a conclusion from what it did not.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
TAURI = ROOT / "desktop" / "src-tauri"
PERMISSIONS_DIR = TAURI / "permissions"
CAPABILITIES_DIR = TAURI / "capabilities"
LAUNCHER = TAURI / "src" / "main.rs"
SOURCE_DIR = TAURI / "src"

# Tauri's `dynamic-acl` feature lets a running application hand itself a new
# capability through `Manager::add_capability`, and it is in tauri's OWN default
# feature list, so it is compiled in whether or not we asked for it. A grant
# made that way exists only for the life of the process and appears in no file
# under capabilities/, which is where a reviewer looks. These two names are the
# whole surface: `add_capability` is the call, `RuntimeCapability` is the trait
# its argument implements.
RUNTIME_ACL_NAMES = ("add_capability", "RuntimeCapability")

# The commands the application page actually invokes, each of which is dead on
# the loopback origin unless a remote capability grants it.
#
# `open_external_url` is every outbound link, reached from `openExternalUrl` in
# frontend/src/shared/lib/desktop.ts. `open_app_in_browser` is the header menu
# item and the desktop toolbar button. The two update-check commands are the
# buttons on the update notice, which now report a refusal instead of hiding
# themselves, so dropping their grant turns a working notice into a visibly
# broken one rather than into nothing.
#
# `open_log_file` and `get_app_url` are deliberately absent: the launcher shell
# calls them, the application page does not, and a command nobody calls does not
# need a remote grant.
#
# The two server-choice commands are the settings card that points this install
# at a server the organisation already runs. They are listed for the same reason
# as the update-check pair: losing the grant does not raise anything, it turns
# the card from an editor into the read-only panel that remote mode is supposed
# to show, and a local install would then look like it had been centrally
# managed by nobody. `use_local_server` is deliberately not here. It is the way
# back from a server that cannot be reached, it is called from the launcher's own
# failure screen over the Tauri protocol, and no web origin gets it.
APP_WINDOW_COMMANDS = (
    "open_external_url",
    "open_app_in_browser",
    "set_update_check_enabled",
    "decline_update_version",
    "get_server_choice",
    "set_server_choice",
)

# Prefixed (plugin or core) permissions a remote capability may carry anyway,
# each with its reason next to it. Every other prefixed identifier is still
# refused below. The bar for this list is that the permission reaches nothing
# beyond how this window presents itself: no file, no process, no network.
#
# `core:webview:allow-set-webview-zoom` sets the zoom factor of a webview, and
# this launcher has one. It is how the Text size choice in Settings applies
# native zoom (`setDesktopWebviewZoom` in frontend/src/shared/lib/desktop.ts),
# and on macOS and Linux the `zoomHotkeysEnabled` polyfill Tauri injects calls
# the same command for the zoom shortcuts, so without it those keys are refused
# there. The worst a page can do with it is magnify itself.
REMOTE_PLUGIN_PERMISSIONS_ALLOWED = frozenset({"core:webview:allow-set-webview-zoom"})

# The functions the Windows link-opening path is made of. Named rather than
# discovered, because a scope that grows by itself cannot go stale and therefore
# cannot tell you it has. If one of these is renamed or split, this gate fails
# saying it can no longer find the path, which is the correct thing to say.
OPENER_FUNCTIONS = ("open_with_os_default", "shell_target", "shell_execute")

# Ways to get a child process in this crate. `raw_arg` is here because it is not
# a way to start one at all: it exists to write a command line without escaping,
# which is precisely what handed cmd.exe an address to re-parse.
PROCESS_BUILDER_RE = re.compile(r"Command::new|\.raw_arg\b|CreateProcess[AW]?\b|ShellExecuteEx[AW]?\b")

# Programs that take a string and interpret it before doing anything with it.
# The launcher legitimately starts `open`, `xdg-open`, `kill`, `taskkill` and
# `node`, and none of those re-parses its arguments; these do.
SHELL_PROGRAM_RE = re.compile(
    r"""Command::new\(\s*"(?:[^"]*[/\\])?(cmd|cmd\.exe|command\.com|powershell"""
    r"""|powershell\.exe|pwsh|pwsh\.exe|sh|bash|zsh|dash)"\s*\)"""
)

DEFAULT_PORTS = {"http": 80, "https": 443}

# Ports the launcher can pick at runtime: the stable default when it is free,
# and anything else when it is not. A grant that only covers one of these is a
# grant that works on some machines.
SAMPLE_PORTS = (8732, 1024, 49512, 65535)

# Measured against tauri_utils::acl::RemoteUrlPattern (tauri-utils 2.9.3), which
# is what decides this at runtime. Each row is pattern, address, expected match.
MATCHER_SELF_TEST = (
    ("http://127.0.0.1:*", "http://127.0.0.1:8732/", True),
    ("http://127.0.0.1:*", "http://127.0.0.1:49512/", True),
    ("http://127.0.0.1:*", "http://127.0.0.1:49512/boq/123?a=1#b", True),
    ("http://127.0.0.1:*", "http://127.0.0.1.evil.invalid/", False),
    ("http://127.0.0.1:*", "http://evil.invalid/", False),
    ("http://127.0.0.1:*", "https://127.0.0.1:8732/", False),
    ("http://127.0.0.1:*", "http://192.168.1.5:8732/", False),
    ("http://127.0.0.1:*", "http://localhost:8732/", False),
    ("http://localhost:*", "http://localhost:8732/boq?a=1", True),
    ("http://localhost:*", "http://127.0.0.1:8732/", False),
    ("http://127.0.0.1:*/*", "http://127.0.0.1:8732/", True),
    ("http://127.0.0.1:8732", "http://127.0.0.1:8732/", True),
    ("http://127.0.0.1:8732", "http://127.0.0.1:49512/", False),
)

PATTERN_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.\-]*)://(?P<host>[^/:]+)(?::(?P<port>[^/]+))?(?P<path>/.*)?\Z")

# The address the launcher hands the webview, and only that. The API calls in
# the same file are written as `http://127.0.0.1:{port}/api/health` and friends,
# so requiring the format string to end right after the root slash separates the
# page origin from the requests the launcher makes on its own behalf.
APP_ORIGIN_RE = re.compile(r'format!\("http://(?P<host>[^"/:]+):\{[A-Za-z_][A-Za-z0-9_]*\}/"\)')

HANDLER_RE = re.compile(r"generate_handler!\[(?P<body>.*?)\]", re.DOTALL)

COMMENT_RE = re.compile(r"//.*$", re.MULTILINE)


def pattern_matches(pattern: str, url: str) -> bool:
    """Does `pattern` cover `url`, for the subset of URLPattern Tauri needs here.

    Supports `*` in the host and the port, and a `/*` or absent path meaning any
    path. Anything richer than that is refused rather than guessed at, because a
    pattern this cannot reason about is one nobody reading the capability file
    can reason about either.
    """
    parsed = PATTERN_RE.fullmatch(pattern)
    if parsed is None:
        return False
    target = urlsplit(url)

    if parsed["scheme"] != target.scheme:
        return False

    host = parsed["host"]
    if host != "*" and host.lower() != (target.hostname or "").lower():
        return False

    port = parsed["port"]
    target_port = target.port if target.port is not None else DEFAULT_PORTS.get(target.scheme)
    if port is None:
        if target_port != DEFAULT_PORTS.get(parsed["scheme"]):
            return False
    elif port != "*" and (not port.isdigit() or int(port) != target_port):
        return False

    path = parsed["path"]
    if path in (None, "", "/", "/*"):
        return True
    if path.endswith("/*"):
        return target.path.startswith(path[:-1])
    return target.path == path


def self_test_matcher() -> list[str]:
    """Prove the matcher still answers the way the real one does."""
    return [
        f"matcher disagrees with tauri_utils: {pattern!r} vs {url} said "
        f"{pattern_matches(pattern, url)}, RemoteUrlPattern says {expected}"
        for pattern, url, expected in MATCHER_SELF_TEST
        if pattern_matches(pattern, url) is not expected
    ]


def load_permission_files() -> tuple[dict[str, set[str]], dict[str, list[str]], int]:
    """Read the application's own permission definitions off disk.

    Returns the command set each permission allows, the members of each
    permission set, and how many files were read.
    """
    commands: dict[str, set[str]] = {}
    sets: dict[str, list[str]] = {}
    files = sorted(p for p in PERMISSIONS_DIR.rglob("*") if p.suffix in {".json", ".toml"})

    for path in files:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if path.suffix == ".json" else tomllib.loads(raw)
        for permission in data.get("permission", []):
            allowed = permission.get("commands", {}).get("allow", [])
            commands[permission["identifier"]] = set(allowed)
        for group in data.get("set", []):
            sets[group["identifier"]] = list(group.get("permissions", []))
        default = data.get("default")
        if isinstance(default, dict):
            sets["default"] = list(default.get("permissions", []))

    return commands, sets, len(files)


def resolve(identifier: str, commands: dict[str, set[str]], sets: dict[str, list[str]]) -> set[str]:
    """Every command an identifier grants, following permission sets."""
    seen: set[str] = set()
    pending = [identifier]
    granted: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        granted |= commands.get(current, set())
        pending.extend(sets.get(current, []))
    return granted


def load_capabilities() -> list[tuple[Path, dict]]:
    """Every capability the desktop build ships, with the file it came from."""
    found: list[tuple[Path, dict]] = []
    for path in sorted(CAPABILITIES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else [data]
        found.extend((path, entry) for entry in entries)
    return found


def handler_commands() -> set[str]:
    """The commands the launcher registers, as written in generate_handler!."""
    source = COMMENT_RE.sub("", LAUNCHER.read_text(encoding="utf-8"))
    names: set[str] = set()
    for block in HANDLER_RE.finditer(source):
        for raw in block["body"].split(","):
            name = raw.strip().split("::")[-1]
            if name:
                names.add(name)
    return names


def app_origin_addresses() -> tuple[set[str], list[str]]:
    """Sample addresses the launcher can navigate the webview to."""
    source = LAUNCHER.read_text(encoding="utf-8")
    hosts = {match["host"] for match in APP_ORIGIN_RE.finditer(source)}
    addresses = [f"http://{host}:{port}/" for host in sorted(hosts) for port in SAMPLE_PORTS]
    addresses += [f"http://{host}:{SAMPLE_PORTS[0]}/boq/123?tab=items#row" for host in sorted(hosts)]
    return hosts, addresses


def runtime_acl_call_sites() -> list[str]:
    """Find code under the desktop crate that grants a capability at runtime.

    Comment lines are skipped so this file's own reasoning, and any doc comment
    that names the feature in order to explain why it is avoided, can say the
    words without tripping the check. Real calls do not live on comment lines.
    The narrower reading is deliberate: a gate nobody can describe in prose
    without breaking it gets described wrongly instead, or switched off.

    Returns:
        One ``path:line: text`` string per occurrence, empty when there are none.
    """
    found: list[str] = []
    for path in sorted(SOURCE_DIR.rglob("*.rs")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            for name in RUNTIME_ACL_NAMES:
                if re.search(rf"\b{name}\b", line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {stripped[:100]}")
                    break
    return found


def windows_opener_bodies(source: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Pull out the Windows arms of the link-opening functions, with line numbers.

    A top level Rust function ends at the next ``}`` in the first column, which
    is enough structure for this and needs no parser. Only arms carrying a
    ``target_os = "windows"`` attribute are returned: the other arms of
    ``open_with_os_default`` spawn ``open`` and ``xdg-open`` quite legitimately,
    and a check that flagged them would be describing the wrong platform.

    ``not(...)`` is stripped before that attribute is read, and this is not
    hypothetical tidiness. ``#[cfg(not(target_os = "windows"))]`` contains the
    string ``target_os = "windows"``, so matching on the substring alone
    collected the arm that means the exact opposite. Two arms share a name, and
    the negated one is written second, so it quietly displaced the arm that was
    supposed to be under inspection. A test asserting the non-Windows arm is
    ignored is what caught it.

    Returned as a list of pairs rather than a mapping for the same reason: two
    bodies under one name must both be scanned, not silently reduced to one.

    Args:
        source: The whole text of one Rust file.

    Returns:
        One (name, lines) pair per Windows arm, each line as (number, text).
    """
    lines = source.splitlines()
    found: list[tuple[str, list[tuple[int, str]]]] = []

    for index, line in enumerate(lines):
        match = re.match(r"(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if not match or match.group(1) not in OPENER_FUNCTIONS:
            continue

        # Attributes sit above the signature, one per line, until something
        # that is neither an attribute nor a doc comment.
        windows_only = False
        back = index - 1
        while back >= 0:
            above = lines[back].strip()
            if above.startswith("#["):
                positive = re.sub(r"not\s*\([^)]*\)", "", above)
                windows_only = windows_only or 'target_os = "windows"' in positive
            elif not above.startswith("///") and above:
                break
            back -= 1
        if not windows_only:
            continue

        body: list[tuple[int, str]] = []
        for number in range(index, len(lines)):
            body.append((number + 1, lines[number]))
            if number > index and lines[number].startswith("}"):
                break
        found.append((match.group(1), body))

    return found


def opener_shell_sites() -> tuple[list[str], list[str]]:
    """Find any process construction in the opener, or any shell in the crate.

    Returns:
        Two lists of ``path:line: text`` strings. The first is process
        construction inside the Windows link-opening path, where there should be
        none at all. The second is a program that re-parses its arguments,
        anywhere in the crate.
    """
    in_opener: list[str] = []
    shells: list[str] = []

    for path in sorted(SOURCE_DIR.rglob("*.rs")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)

        for name, body in windows_opener_bodies(source):
            for number, line in body:
                stripped = line.strip()
                if stripped.startswith("//") or not PROCESS_BUILDER_RE.search(line):
                    continue
                in_opener.append(f"{relative}:{number}: in {name}(): {stripped[:90]}")

        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("//") and SHELL_PROGRAM_RE.search(line):
                shells.append(f"{relative}:{number}: {stripped[:90]}")

    return in_opener, shells


def main() -> int:
    problems = self_test_matcher()
    if problems:
        print("The URL pattern matcher in this gate no longer agrees with the one Tauri uses.")
        for problem in problems:
            print(f"  {problem}")
        print(
            "\nUntil that is fixed this check cannot tell a working grant from a broken one,\n"
            "so it refuses rather than reporting a pass it did not earn."
        )
        return 1

    runtime_grants = runtime_acl_call_sites()
    if runtime_grants:
        print("The desktop crate grants itself a capability at runtime:")
        for site in runtime_grants:
            print(f"  {site}")
        print(
            "\nA capability added through Manager::add_capability exists only while the process\n"
            "runs and is written down nowhere. Everything a reviewer reads to answer 'what may\n"
            "the application window call' lives in desktop/src-tauri/capabilities/, and a\n"
            "runtime grant is invisible there, so the files would keep describing a narrower\n"
            "application than the one that ships. Tauri compiles this in by default, which is\n"
            "why the absence of it is worth checking rather than assuming.\n"
            "\nDeclare the grant in a capability file instead. If a runtime grant is genuinely\n"
            "needed, that is a decision to make deliberately and record here, not one to let\n"
            "through on the strength of the code compiling."
        )
        return 1

    # What the scan found, asserted before anything is concluded from what it
    # did not find. A scope that has gone stale reports nothing and looks
    # exactly like a clean tree.
    opener_bodies = windows_opener_bodies(LAUNCHER.read_text(encoding="utf-8"))
    opener_names = [name for name, _ in opener_bodies]
    missing = [name for name in OPENER_FUNCTIONS if name not in opener_names]
    if missing:
        print("This gate can no longer find the Windows link-opening path: " + ", ".join(missing))
        print(
            f"\nIt looks for {', '.join(OPENER_FUNCTIONS)} in "
            f'{LAUNCHER.relative_to(ROOT)}, each carrying a target_os = "windows"\n'
            "attribute. One of them has been renamed, split, moved to another file or had its\n"
            "attribute changed, so the check below is now reading nothing and would pass\n"
            "whatever the opener does.\n"
            "\nPoint OPENER_FUNCTIONS at whatever the path is called now. Do not delete the\n"
            "check: an empty scope is the one failure it cannot report on its own, which is\n"
            "why it is reported here instead."
        )
        return 1

    in_opener, shells = opener_shell_sites()
    if in_opener or shells:
        if in_opener:
            print("The link-opening path constructs a process:")
            for site in in_opener:
                print(f"  {site}")
        if shells:
            print("A program that re-parses its arguments is started here:")
            for site in shells:
                print(f"  {site}")
        print(
            '\nOpening a link on Windows used to run cmd /c start "" "<target>", which made the\n'
            "address part of a command line cmd.exe then re-parsed. Quoting stopped the command\n"
            "separators and did nothing about percent expansion: cmd substitutes %NAME% inside\n"
            "double quotes as readily as outside, so %USERNAME% in a link became the account\n"
            "name and %CD% became the full path of the working directory, both sent to whatever\n"
            "host the link named. Six of seven names measured expanded, and only one of those\n"
            "was in the process environment block, so no denylist was ever going to close it.\n"
            "\nThe opener hands the target to ShellExecuteW as a single argument, and the whole\n"
            "point is that nothing between the caller and the operating system parses it. Use\n"
            "open_with_os_default rather than starting a process, and if a process is genuinely\n"
            "needed, pass the target as an argument rather than building a command line."
        )
        return 1

    if not PERMISSIONS_DIR.is_dir():
        print(f"{PERMISSIONS_DIR.relative_to(ROOT)} does not exist.")
        print(
            "\nThe desktop application defines no permissions of its own, so no capability can\n"
            "name one, so the application window - which Tauri treats as a remote origin - is\n"
            "refused every command it invokes. Every outbound link in the product is dead and\n"
            "silent in that state."
        )
        return 1

    commands, sets, permission_file_count = load_permission_files()
    capabilities = load_capabilities()
    handlers = handler_commands()
    hosts, addresses = app_origin_addresses()

    if not hosts:
        print("Could not find the address the launcher navigates the webview to.")
        print(
            f"\nThis gate reads it out of {LAUNCHER.relative_to(ROOT)}, looking for a format string\n"
            'written exactly as format!("http://<host>:{<port>}/"). If the launcher now builds\n'
            "that address some other way, teach this check the new shape; it cannot check a\n"
            "grant against an address it cannot find."
        )
        return 1

    granted_anywhere: set[str] = set()
    remote_grants: list[tuple[Path, dict, set[str]]] = []
    prefixed_remote: list[str] = []

    for path, capability in capabilities:
        allowed: set[str] = set()
        for entry in capability.get("permissions", []):
            identifier = entry if isinstance(entry, str) else entry.get("identifier", "")
            if ":" in identifier:
                if capability.get("remote") and identifier not in REMOTE_PLUGIN_PERMISSIONS_ALLOWED:
                    prefixed_remote.append(f"{path.name}: {capability.get('identifier')} -> {identifier}")
                continue
            allowed |= resolve(identifier, commands, sets)
        granted_anywhere |= allowed
        if capability.get("remote"):
            remote_grants.append((path, capability, allowed))

    ungranted = sorted(handlers - granted_anywhere)
    if ungranted:
        print("Commands the launcher registers that no capability grants: " + ", ".join(ungranted))
        print(
            "\nThe desktop application declares its own ACL, which means Tauri checks app\n"
            "commands on the local origin too, not only on the loopback origin the application\n"
            "window runs on. A registered command with no permission behind it is refused\n"
            f"wherever it is called from. Add a permission under {PERMISSIONS_DIR.relative_to(ROOT)}\n"
            "and name it from the capability whose origin needs it."
        )
        return 1

    covering = [
        (path, capability, allowed)
        for path, capability, allowed in remote_grants
        if any(
            pattern_matches(pattern, address)
            for pattern in capability.get("remote", {}).get("urls", [])
            for address in addresses
        )
    ]

    unreachable = sorted(
        command for command in APP_WINDOW_COMMANDS if not any(command in allowed for _, _, allowed in covering)
    )

    if unreachable:
        print("Commands the application window invokes that it cannot reach: " + ", ".join(unreachable))
        print(
            f"\nThe launcher navigates the webview to one of {sorted(hosts)} on a port it picks at\n"
            "runtime, and Tauri classifies that as a remote origin. A capability therefore needs\n"
            'a "remote" block whose URL patterns cover that address, and permissions that resolve\n'
            "to each command the page invokes. Without both, the control that calls it does\n"
            "nothing at all: the command is refused before it runs.\n"
            "\nA grant being present for one command says nothing about the others, so each is\n"
            "checked on its own. If one of these is genuinely no longer called from the page,\n"
            "take it out of APP_WINDOW_COMMANDS in the same commit that takes out the call.\n"
            f"\nCapabilities carrying a remote block: {len(remote_grants)}, of which\n"
            f"{len(covering)} cover the launcher address.\n"
            f"Addresses checked: {', '.join(addresses[:4])} and {len(addresses) - 4} more."
        )
        return 1

    reaching = [
        (path, capability)
        for path, capability, allowed in covering
        if any(command in allowed for command in APP_WINDOW_COMMANDS)
    ]

    if prefixed_remote:
        print("A remote origin is being granted a plugin permission: " + "; ".join(prefixed_remote))
        print(
            "\nA capability with a remote block describes what content served over the network may\n"
            "do. Application commands are written by us and validate their own arguments; plugin\n"
            "permissions are broader by design, and shell or process access handed to a remote\n"
            "origin is a different decision from letting a page open a link. Grant an application\n"
            "permission instead, or make the case for this one deliberately."
        )
        return 1

    names = ", ".join(sorted(capability.get("identifier", path.name) for path, capability in reaching))
    print(
        f"desktop link ACL: {permission_file_count} permission file(s) define "
        f"{len(commands)} permission(s) and {len(sets)} set(s); "
        f"all {len(handlers)} registered command(s) are granted; "
        f"all {len(APP_WINDOW_COMMANDS)} command(s) the application page invokes "
        f"({', '.join(APP_WINDOW_COMMANDS)}) reach it through {names}; "
        f"the {len(opener_bodies)} function(s) of the Windows link-opening path "
        f"start no process and the crate starts no shell."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
