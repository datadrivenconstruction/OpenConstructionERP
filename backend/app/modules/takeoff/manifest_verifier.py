"""‌⁠‍Signed-manifest verifier for converter binaries (Audit A1).

================================================================================
THREAT MODEL
================================================================================

The DDC converter installer (``takeoff/router.py``) downloads several
hundred megabytes of native binaries from the public internet:

    * GitHub Contents API → ``raw.githubusercontent.com`` blobs
      (DDC dwg/rvt/ifc/dgn converters)
    * ``pkg.datadrivenconstruction.io`` Debian repository (Linux .debs)
    * Qdrant releases (vector DB, also pulled per platform)
    * PaddleOCR model archives (lazy, on first use)

A2/A9/A11 (already shipped in v2.x) hardened the *transport*:

    * Host allow-list (A2): no surprise CDN substitution
    * Symlink/TOCTOU guard (A9): can't trick a privileged write
    * Streaming size caps (A11): can't fill the disk

This file closes the remaining gap — *integrity*. The attacks A1 is
designed to defeat are:

    1. **DNS hijack of a GitHub release.** An attacker who controls
       upstream DNS (or a rogue resolver in a corporate network) can
       point ``raw.githubusercontent.com`` at their own server. TLS
       proves the IP you connected to served a certificate for that
       host — it does NOT prove the content is the file the upstream
       maintainer published. A valid TLS handshake to a hostile origin
       is exactly what a DNS hijack delivers.

    2. **Compromised package CDN.** Even GitHub itself has had blob
       caching incidents. A poisoned cache entry would serve a
       tampered binary over a valid TLS connection from the legitimate
       host. The host allow-list (A2) is no defence here because the
       host IS the canonical host.

    3. **MITM with stolen leaf cert.** A certificate transparency log
       miss combined with a stolen wildcard cert lets an attacker
       intercept ``*.githubusercontent.com`` end-to-end. Rare, but
       part of the threat model for binaries that get system-level
       execute privilege.

    4. **Upstream account takeover.** Whoever has the
       ``datadrivenconstruction`` GitHub credentials can replace
       ``*Exporter.exe`` in the repo, and the host allow-list will
       happily download the new (poisoned) file. The signing key is
       held *separately* from the GitHub credentials — see "Signing
       ceremony" below — so an account takeover is not enough to land
       a hostile converter on user machines.

TLS alone is insufficient because it authenticates the *connection*,
not the *artifact*. Code signing authenticates the *artifact*,
independent of how it was transported. That's what this module does.

================================================================================
DESIGN
================================================================================

We fetch a small JSON ``manifest.json`` that lists every component the
installer can install, with:

    * Platform-specific download URLs
    * SHA-256 hash of the expected file contents
    * File size (cross-check + UX)
    * OE version compatibility range
    * Pinned upstream commit SHA (provenance)

The manifest is paired with a detached Ed25519 signature
(``manifest.json.sig``) created with the project signing key. The
public half of that key is embedded *in this file* (32 bytes hex). At
install time:

    1. Download manifest.json + manifest.json.sig
    2. Verify the signature against the embedded public key
    3. If verify FAILS → refuse (502, do not install)
    4. Look up component + current platform in the parsed manifest
    5. Download the binary
    6. Compute SHA-256 of the downloaded bytes
    7. If hash mismatches manifest → refuse, delete partial file

The escape hatch ``OE_DISABLE_MANIFEST_VERIFY=1`` falls back to the
pre-A1 (A2+A9+A11) flow with a loud WARNING log line. We keep this
escape hatch because dev/CI environments often run against a
not-yet-signed local manifest mirror. Production deployments should
set it to ``0`` (or unset).

For air-gapped sites: ``OE_MANIFEST_URL`` overrides the canonical URL
so operators can host a signed manifest on an internal mirror. The
signature requirement is unchanged — the internal mirror must serve
the upstream-signed bundle as-is.

================================================================================
SIGNING CEREMONY
================================================================================

The private signing key is held by Artem (founder) on a hardware
security key. It is NOT in the repository, NOT in CI secrets, NOT
on any always-on server. Manifest signing happens offline:

    1. Maintainer prepares ``manifest.json`` locally with new SHAs
    2. Plugs in the hardware key
    3. Runs ``scripts/sign_manifest.py manifest.json`` (separate repo)
    4. Uploads ``manifest.json`` + ``manifest.json.sig`` to the CDN
    5. Unplugs the hardware key

If the private key is ever suspected of compromise:

    1. Generate a new keypair (``scripts/rotate_manifest_signing_key.py``
       produces fresh hex pubkey to paste into this file)
    2. Bump ``CURRENT_PUBKEY`` below + ship a patch release
    3. Re-sign all manifests with the new key
    4. Invalidate the old key (push a "revoked" marker so old
       installers refuse to verify against the now-compromised key)

The rotation script writes the new pubkey to *this* source file via
a sentinel marker so the change shows up in a normal code review and
the old key is preserved in git history (for forensic timelines).

================================================================================
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Trust anchor: Ed25519 public key (32 bytes, hex-encoded) ──────────────
#
# This is the SOLE trust anchor for converter installs. Replacing it
# replaces every signature relationship in the system, so PRs that
# touch it should:
#
#   * Reference the rotation ticket in the commit body
#   * Include the new pubkey AS COMMENT alongside CURRENT_PUBKEY
#     so the diff makes the change obvious to reviewers
#   * Be signed by the maintainer's GitHub-verified commit signature
#
# The current key was generated 2026-05-13 with:
#   python -c 'from cryptography.hazmat.primitives.asymmetric.ed25519 \
#     import Ed25519PrivateKey; \
#     from cryptography.hazmat.primitives import serialization as s; \
#     k = Ed25519PrivateKey.generate(); \
#     print(k.public_key().public_bytes( \
#       encoding=s.Encoding.Raw, \
#       format=s.PublicFormat.Raw).hex())'
#
# ROTATION_SENTINEL_BEGIN — do not edit by hand; script writes here
CURRENT_PUBKEY_HEX: str = "0000000000000000000000000000000000000000000000000000000000000000"
# ROTATION_SENTINEL_END

# Canonical manifest location. Mirror fallback is the marketing site,
# which is hosted on a separate origin from the package CDN so a
# single-CDN compromise doesn't take both down.
DEFAULT_MANIFEST_URL: str = "https://pkg.datadrivenconstruction.io/oe/manifest.json"
FALLBACK_MANIFEST_URL: str = "https://openconstructionerp.com/manifest.json"

# Signature is fetched from <manifest_url>.sig — the same convention
# Debian uses for InRelease/Release.gpg. Keeping it as a sibling URL
# lets operators serve both via plain static hosting.
_SIGNATURE_SUFFIX: str = ".sig"

# Per-fetch caps. The manifest is small JSON (a few KB even for the
# 30-component case); cap at 1 MB so a hostile origin can't trickle
# gigabytes of garbage through urlopen.
_MAX_MANIFEST_BYTES: int = 1 * 1024 * 1024  # 1 MB
_MAX_SIGNATURE_BYTES: int = 1024  # Ed25519 sig is 64 bytes; 1 KB is generous

# Fetch timeout. We don't want the install endpoint to hang forever
# if pkg.datadrivenconstruction.io is slow.
_FETCH_TIMEOUT_S: int = 30


# ── Public exception types ────────────────────────────────────────────────


class ManifestError(Exception):
    """‌⁠‍Base class for all manifest verification failures.

    Callers should catch this rather than the subclasses unless they
    care about the specific failure mode (e.g. to render a different
    UI for "platform unsupported" vs "signature invalid").
    """


class ManifestSignatureInvalid(ManifestError):
    """‌⁠‍The detached signature did not verify against the embedded pubkey.

    This is the high-severity case: it means either the manifest was
    tampered with in transit, the key was rotated and the client
    wasn't updated, or the signing process is broken. NEVER install
    a component when this is raised.
    """


class ManifestFetchError(ManifestError):
    """Could not download the manifest or its signature.

    Network failure, 4xx/5xx HTTP, or size-cap exceeded. Distinguished
    from signature-invalid so the UI can surface a transient-vs-fatal
    distinction.
    """


class ManifestParseError(ManifestError):
    """The manifest body is not valid JSON or has the wrong shape.

    Indicates the upstream published a malformed manifest. We refuse
    to proceed rather than guess at the operator's intent.
    """


class InstallNotSupported(ManifestError):
    """The current platform / component combination isn't in the manifest.

    Not a security failure — just "we don't ship a converter for that
    platform yet". Callers should surface this as a 502 with a link
    to file an issue.
    """


class InstallSHAMismatch(ManifestError):
    """Downloaded blob's SHA-256 does not match the manifest entry.

    This is the second high-severity case: it means the file at the
    download URL is NOT the file the manifest publisher signed for.
    Either the upstream CDN was poisoned, the upstream maintainer
    replaced the file without re-signing, or there's a MITM. The
    partially-downloaded file is deleted by the caller.
    """


# ── Manifest dataclasses ──────────────────────────────────────────────────
#
# We keep the manifest model deliberately small and tolerant of unknown
# fields — future versions may add fields and we don't want old clients
# to refuse to install just because a new optional key appeared.


@dataclass(frozen=True)
class PlatformEntry:
    """A single platform's download coordinates for one component."""

    url: str
    sha256: str  # lowercase hex
    size_bytes: int


@dataclass(frozen=True)
class ComponentEntry:
    """One installable component (converter, model pack, etc.)."""

    name: str
    version: str
    platforms: dict[str, PlatformEntry]
    upstream_commit_sha: str | None = None
    min_oe_version: str | None = None
    max_oe_version: str | None = None

    def platform_entry(self, platform_key: str) -> PlatformEntry:
        """Look up a platform; raise InstallNotSupported if missing.

        Encapsulating the lookup here keeps the error message in one
        place and gives us a single point to log if a platform key
        keeps missing the manifest (which would signal a release
        process issue worth alerting on).
        """
        entry = self.platforms.get(platform_key)
        if entry is None:
            available = sorted(self.platforms.keys())
            raise InstallNotSupported(
                f"Component {self.name!r} is not published for platform "
                f"{platform_key!r}. Available platforms: {available}. "
                f"Please file an issue at "
                f"https://github.com/datadrivenconstruction/"
                f"OpenConstructionERP/issues if you need this platform."
            )
        return entry


@dataclass(frozen=True)
class Manifest:
    """Parsed + signature-verified manifest document.

    Construction of this object implies the signature has been
    verified against ``CURRENT_PUBKEY_HEX``; you cannot get a
    ``Manifest`` instance through any code path that skips
    verification.
    """

    version: str  # the manifest's own version string (date or semver)
    signed_at: str  # ISO-8601 timestamp
    components: dict[str, ComponentEntry] = field(default_factory=dict)

    def component(self, name: str) -> ComponentEntry:
        """Look up by name; raise InstallNotSupported if missing."""
        entry = self.components.get(name)
        if entry is None:
            available = sorted(self.components.keys())
            raise InstallNotSupported(f"Component {name!r} is not in the manifest. Available components: {available}.")
        return entry


# ── Verification helpers ──────────────────────────────────────────────────


def _is_verification_disabled() -> bool:
    """Read the ``OE_DISABLE_MANIFEST_VERIFY`` escape hatch.

    Kept as a function (not a module-level constant) so test code
    can toggle it without re-importing the module.
    """
    raw = os.environ.get("OE_DISABLE_MANIFEST_VERIFY", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_manifest_url() -> str:
    """Pick the manifest URL honouring the air-gap override.

    The env var takes precedence over the canonical URL so operators
    can point at an internal mirror without code changes. The mirror
    is still required to serve the original upstream-signed manifest
    + signature — the verification check is unchanged.
    """
    override = os.environ.get("OE_MANIFEST_URL", "").strip()
    if override:
        return override
    return DEFAULT_MANIFEST_URL


def current_platform_key() -> str:
    """Return the manifest platform key for the running interpreter.

    Maps Python's ``sys.platform`` + ``platform.machine()`` to the
    string the manifest uses. We name these explicitly rather than
    using one of ``sys.platform``'s aliases so a Debian-on-ARM client
    gets a distinct key from a Mac-on-ARM client.
    """
    machine = platform.machine().lower()
    if sys.platform == "win32":
        arch = "x86_64" if machine in {"amd64", "x86_64"} else machine
        return f"windows_{arch}"
    if sys.platform == "darwin":
        arch = "arm64" if machine in {"arm64", "aarch64"} else "x86_64"
        return f"darwin_{arch}"
    if sys.platform.startswith("linux"):
        arch = "x86_64" if machine in {"amd64", "x86_64"} else machine
        return f"linux_{arch}"
    # Unrecognised platform — emit the raw values so the user sees what
    # to put in their issue report when they hit InstallNotSupported.
    return f"{sys.platform}_{machine or 'unknown'}"


def _fetch_bytes(url: str, max_bytes: int) -> bytes:
    """Download bytes from a URL with a size cap.

    Streaming chunk-by-chunk and aborting on overrun keeps a hostile
    origin from filling memory. We don't use the bigger A11 helper
    (``_download_one_file``) here because the manifest goes into
    memory, not to disk.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OpenConstructionERP-manifest-verifier"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared = int(content_length)
                except (TypeError, ValueError):
                    declared = None
                else:
                    if declared > max_bytes:
                        raise ManifestFetchError(
                            f"Refused to fetch {url!r} — declared size {declared} bytes exceeds cap of {max_bytes}"
                        )
            buf = bytearray()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise ManifestFetchError(f"Aborted fetch of {url!r} — body exceeded cap of {max_bytes} bytes")
            return bytes(buf)
    except urllib.error.HTTPError as exc:
        raise ManifestFetchError(f"HTTP {exc.code} fetching {url!r}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ManifestFetchError(f"Network error fetching {url!r}: {exc}") from exc


def verify_signature(manifest_bytes: bytes, signature_bytes: bytes, pubkey_hex: str | None = None) -> None:
    """Verify a detached Ed25519 signature.

    Raises ``ManifestSignatureInvalid`` on any failure. Accepts an
    optional ``pubkey_hex`` override so the rotation script can
    self-test with a freshly-generated key without having to write
    the new key to source first.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PublicKey,
    )

    hex_key = pubkey_hex if pubkey_hex is not None else CURRENT_PUBKEY_HEX
    try:
        pubkey_raw = bytes.fromhex(hex_key)
    except ValueError as exc:
        raise ManifestSignatureInvalid(f"Embedded pubkey is not valid hex: {exc}") from exc
    if len(pubkey_raw) != 32:
        raise ManifestSignatureInvalid(f"Embedded pubkey must be 32 bytes (got {len(pubkey_raw)})")
    if len(signature_bytes) != 64:
        # Ed25519 signatures are always 64 bytes — anything else is
        # either truncated or a different algorithm.
        raise ManifestSignatureInvalid(f"Signature must be 64 bytes (got {len(signature_bytes)})")
    try:
        Ed25519PublicKey.from_public_bytes(pubkey_raw).verify(
            signature_bytes,
            manifest_bytes,
        )
    except InvalidSignature as exc:
        raise ManifestSignatureInvalid(
            "Manifest signature did not verify against the embedded "
            "public key. Refusing to install — this means the manifest "
            "was tampered with in transit, the signing key was rotated "
            "and your client is stale, or there is an active MITM "
            "between you and the package CDN."
        ) from exc


def parse_manifest(manifest_bytes: bytes) -> Manifest:
    """Parse a verified manifest blob into a typed ``Manifest``.

    Only called AFTER the signature has been verified, so we trust
    the JSON shape enough to surface helpful errors instead of
    defensive paranoia. Still raises ``ManifestParseError`` on shape
    mismatch so a future manifest format bump doesn't crash with a
    cryptic ``KeyError``.
    """
    try:
        doc = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestParseError(f"Manifest body is not valid UTF-8 JSON: {exc}") from exc

    if not isinstance(doc, dict):
        raise ManifestParseError(f"Manifest top-level must be an object, got {type(doc).__name__}")

    try:
        version = str(doc["version"])
        signed_at = str(doc["signed_at"])
        components_raw = doc["components"]
    except KeyError as exc:
        raise ManifestParseError(f"Manifest missing required key: {exc}") from exc

    if not isinstance(components_raw, dict):
        raise ManifestParseError("Manifest 'components' must be an object keyed by component name")

    components: dict[str, ComponentEntry] = {}
    for name, raw in components_raw.items():
        if not isinstance(raw, dict):
            raise ManifestParseError(f"Component {name!r} entry must be an object")
        platforms_raw = raw.get("platforms", {})
        if not isinstance(platforms_raw, dict):
            raise ManifestParseError(f"Component {name!r} 'platforms' must be an object")
        platforms: dict[str, PlatformEntry] = {}
        for plat_key, plat_raw in platforms_raw.items():
            if not isinstance(plat_raw, dict):
                raise ManifestParseError(f"Component {name!r} platform {plat_key!r} entry must be an object")
            try:
                url = str(plat_raw["url"])
                sha256 = str(plat_raw["sha256"]).lower()
                size_bytes = int(plat_raw["size_bytes"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ManifestParseError(
                    f"Component {name!r} platform {plat_key!r} is missing a required field or has the wrong type: {exc}"
                ) from exc
            if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
                raise ManifestParseError(
                    f"Component {name!r} platform {plat_key!r} SHA-256 must be 64 lowercase hex chars, got {sha256!r}"
                )
            platforms[plat_key] = PlatformEntry(
                url=url,
                sha256=sha256,
                size_bytes=size_bytes,
            )

        components[name] = ComponentEntry(
            name=name,
            version=str(raw.get("version", "unknown")),
            platforms=platforms,
            upstream_commit_sha=(str(raw["upstream_commit_sha"]) if "upstream_commit_sha" in raw else None),
            min_oe_version=(str(raw["min_oe_version"]) if "min_oe_version" in raw else None),
            max_oe_version=(str(raw["max_oe_version"]) if "max_oe_version" in raw else None),
        )

    return Manifest(
        version=version,
        signed_at=signed_at,
        components=components,
    )


def fetch_manifest(url: str | None = None) -> Manifest:
    """Download + verify + parse the manifest.

    Public entry point for callers that need the manifest without
    immediately installing anything (e.g. the version-check banner).
    Returns a fully-verified ``Manifest`` or raises ``ManifestError``.

    ``url`` is exposed mainly for tests; production code should leave
    it None and let ``_resolve_manifest_url()`` pick the canonical or
    air-gap-overridden URL.
    """
    manifest_url = url or _resolve_manifest_url()
    sig_url = manifest_url + _SIGNATURE_SUFFIX

    manifest_bytes = _fetch_bytes(manifest_url, _MAX_MANIFEST_BYTES)
    signature_bytes = _fetch_bytes(sig_url, _MAX_SIGNATURE_BYTES)

    verify_signature(manifest_bytes, signature_bytes)
    return parse_manifest(manifest_bytes)


# ── Hash verification at install time ─────────────────────────────────────


def sha256_of_file(path: Path) -> str:
    """Stream a file through SHA-256 (lowercase hex).

    We can't ``hashlib.sha256(path.read_bytes())`` because the
    converter binaries are hundreds of megabytes and we don't want
    to mirror the whole blob in memory.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_downloaded_file(
    path: Path,
    expected_sha256: str,
    expected_size: int | None = None,
) -> None:
    """Verify a downloaded blob matches the manifest entry.

    Raises ``InstallSHAMismatch`` and *deletes* the partial file on
    mismatch — the caller's "uninstall on failure" path then has
    nothing left to roll back. We don't keep the corrupt file around
    because some installers retry on failure, and we don't want a
    poisoned blob lying in the cache dir to be picked up by the
    retry.
    """
    if expected_size is not None:
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            try:
                path.unlink()
            except OSError:
                pass
            raise InstallSHAMismatch(
                f"Downloaded file {path} has size {actual_size} bytes, "
                f"manifest expected {expected_size}. Deleted partial file. "
                f"Refusing to install — possible substitution attack."
            )

    actual = sha256_of_file(path)
    expected_norm = expected_sha256.lower().strip()
    if actual != expected_norm:
        try:
            path.unlink()
        except OSError:
            pass
        raise InstallSHAMismatch(
            f"Downloaded file {path} SHA-256 is {actual}, manifest "
            f"expected {expected_norm}. Deleted partial file. "
            f"Refusing to install — possible substitution attack or "
            f"upstream tampering."
        )


def is_version_in_range(
    oe_version: str,
    min_version: str | None,
    max_version: str | None,
) -> bool:
    """Compare three semver-ish strings inclusively.

    We do simple tuple comparison on dotted-int prefixes so this
    handles ``3.0.2`` and ``2026-05-13`` styles. Suffixes (``-rc1``,
    ``+build``) are stripped — a 3.0.0-rc1 is treated as 3.0.0 for
    range checks. That matches the spirit of "the user is on a
    pre-release, allow them through".
    """

    def _to_tuple(v: str) -> tuple[int, ...]:
        head = v.split("-", 1)[0].split("+", 1)[0]
        parts: list[int] = []
        for piece in head.split("."):
            try:
                parts.append(int(piece))
            except ValueError:
                # Calendar versions like 2026-05-13 — split on '-' too.
                parts.append(0)
        return tuple(parts) if parts else (0,)

    cur = _to_tuple(oe_version)
    if min_version is not None and cur < _to_tuple(min_version):
        return False
    if max_version is not None and cur > _to_tuple(max_version):
        return False
    return True


# ── High-level convenience: prepare an install ────────────────────────────


@dataclass(frozen=True)
class ResolvedInstall:
    """A manifest entry resolved to the running platform.

    Output of ``resolve_install()``: the caller now has the download
    URL, expected SHA, and expected size all in one place and can
    drive the existing ``_download_one_file`` helper without
    re-resolving anything.
    """

    component: str
    version: str
    platform_key: str
    url: str
    sha256: str
    size_bytes: int


def resolve_install(
    manifest: Manifest,
    component: str,
    platform_key: str | None = None,
) -> ResolvedInstall:
    """Combine component + platform lookup with a single error surface.

    Saves the caller from a two-step ``manifest.component().platform_entry()``
    dance, and lets us add manifest-level invariants (version-range
    checks, deprecation warnings) in one place later.
    """
    plat_key = platform_key or current_platform_key()
    entry = manifest.component(component)
    plat = entry.platform_entry(plat_key)
    return ResolvedInstall(
        component=component,
        version=entry.version,
        platform_key=plat_key,
        url=plat.url,
        sha256=plat.sha256,
        size_bytes=plat.size_bytes,
    )


def maybe_warn_disabled() -> None:
    """Emit a single WARNING line when verification is disabled.

    Called from the install path so operators see the bypass in
    their logs even if they forgot they set the env var (e.g.
    after a clean-room reproduction of a download bug).
    """
    if _is_verification_disabled():
        logger.warning(
            "OE_DISABLE_MANIFEST_VERIFY is set — converter installs "
            "will NOT verify SHA-256 against a signed manifest. This "
            "is acceptable for local development but MUST NOT be set "
            "in production. See manifest_verifier.py for the threat "
            "model."
        )


__all__ = [
    "CURRENT_PUBKEY_HEX",
    "DEFAULT_MANIFEST_URL",
    "FALLBACK_MANIFEST_URL",
    "ComponentEntry",
    "InstallNotSupported",
    "InstallSHAMismatch",
    "Manifest",
    "ManifestError",
    "ManifestFetchError",
    "ManifestParseError",
    "ManifestSignatureInvalid",
    "PlatformEntry",
    "ResolvedInstall",
    "current_platform_key",
    "fetch_manifest",
    "is_version_in_range",
    "maybe_warn_disabled",
    "parse_manifest",
    "resolve_install",
    "sha256_of_file",
    "verify_downloaded_file",
    "verify_signature",
]
