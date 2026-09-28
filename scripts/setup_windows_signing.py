#!/usr/bin/env python3
"""Prepare Authenticode signing through Azure Artifact Signing, or stand down.

Called by the Windows legs of ``.github/workflows/desktop-release.yml``. It
decides from which secrets are present, and it is a no-op without them, so the
release pipeline behaves exactly as before until someone configures signing.

Six values, all read from the environment, none ever printed:

    ARTIFACT_SIGNING_ENDPOINT   region endpoint, e.g. https://weu.codesigning.azure.net
    ARTIFACT_SIGNING_ACCOUNT    the Artifact Signing account name
    ARTIFACT_SIGNING_PROFILE    the certificate profile name
    AZURE_TENANT_ID             Entra tenant of the signing app registration
    AZURE_CLIENT_ID             that app registration's client id
    AZURE_CLIENT_SECRET         its client secret

The last three are the names the Azure SDK's EnvironmentCredential reads, which
is how the signing library authenticates: the secret stays in the environment
of the steps that sign and never appears on a command line.

Outcomes, each a different colour on the run page:

* none set: a notice, ``WINDOWS_SIGNING=off``, exit 0. Today's state.
* some set: an error naming the missing ones, exit 1. Half a configuration
  cannot sign anything, and calling the signer with empty values fails with a
  message about the service rather than about the missing secret.
* all set: the signing library is fetched, and ``GITHUB_ENV`` receives
  ``WINDOWS_SIGNING=on``, ``WINDOWS_SIGN_COMMAND`` (a JSON argv for
  ``scripts/sign_windows_binaries.py``) and ``TAURI_SIGN_ARGS`` (a
  ``--config`` pointing at a Tauri config that sets
  ``bundle.windows.signCommand``, so Tauri signs the launcher, the sidecar
  copy, the NSIS plugins, the uninstaller and the installer itself).

Only version tags sign. A run dispatched for a branch builds unsigned whatever
the secrets say, so a test build can never be mistaken for a release.
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

REQUIRED = (
    "ARTIFACT_SIGNING_ENDPOINT",
    "ARTIFACT_SIGNING_ACCOUNT",
    "ARTIFACT_SIGNING_PROFILE",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
)

#: Microsoft's RFC 3161 timestamp authority for Artifact Signing. Mandatory:
#: the certificates live three days, and a timestamp is what keeps the
#: signature valid after that.
TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"

#: The SignTool plugin, published on nuget.org. A .nupkg is a zip file, so it is
#: fetched and opened directly and the runner needs no nuget client.
DLIB_PACKAGE = "Microsoft.ArtifactSigning.Client"
DLIB_NAME = "Azure.CodeSigning.Dlib.dll"

#: Every credential DefaultAzureCredential would otherwise try before the
#: environment one. Excluding them keeps a misconfiguration from being retried
#: through six unrelated mechanisms and reported as the last one's error.
EXCLUDED_CREDENTIALS = [
    "ManagedIdentityCredential",
    "WorkloadIdentityCredential",
    "SharedTokenCacheCredential",
    "VisualStudioCredential",
    "VisualStudioCodeCredential",
    "AzureCliCredential",
    "AzurePowerShellCredential",
    "AzureDeveloperCliCredential",
    "InteractiveBrowserCredential",
]


def classify(env: dict[str, str]) -> tuple[str, list[str]]:
    """Return ``("off"|"partial"|"on", missing_names)``."""
    missing = [name for name in REQUIRED if not env.get(name, "").strip()]
    if len(missing) == len(REQUIRED):
        return "off", missing
    if missing:
        return "partial", missing
    return "on", []


def is_release_ref(ref: str) -> bool:
    """Whether this run releases a version tag (``v18.1.1``), not a branch."""
    return ref.startswith("v") and ref[1:2].isdigit()


def sign_argv(signtool: str, dlib: str, metadata: str) -> list[str]:
    """The SignTool call Microsoft documents for Artifact Signing, file as ``%1``."""
    return [
        signtool,
        "sign",
        "/fd",
        "SHA256",
        "/tr",
        TIMESTAMP_URL,
        "/td",
        "SHA256",
        "/dlib",
        dlib,
        "/dmdf",
        metadata,
        "%1",
    ]


def tauri_config(argv: list[str]) -> dict:
    """A Tauri config fragment merged over tauri.conf.json by ``--config``."""
    return {"bundle": {"windows": {"signCommand": {"cmd": argv[0], "args": argv[1:]}}}}


def metadata(env: dict[str, str]) -> dict:
    return {
        "Endpoint": env["ARTIFACT_SIGNING_ENDPOINT"].strip(),
        "CodeSigningAccountName": env["ARTIFACT_SIGNING_ACCOUNT"].strip(),
        "CertificateProfileName": env["ARTIFACT_SIGNING_PROFILE"].strip(),
        "ExcludeCredentials": EXCLUDED_CREDENTIALS,
    }


def _fetch_dlib(dest: Path) -> Path:
    version = os.environ.get("ARTIFACT_SIGNING_CLIENT_VERSION", "").strip()
    url = f"https://www.nuget.org/api/v2/package/{DLIB_PACKAGE}" + (f"/{version}" if version else "")
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - fixed https URL
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(dest)
    matches = [p for p in dest.rglob(DLIB_NAME) if "x64" in (part.lower() for part in p.parts)]
    if not matches:
        raise FileNotFoundError(f"{DLIB_NAME} for x64 not found in {DLIB_PACKAGE}")
    return matches[0]


def _write_env(lines: dict[str, str]) -> None:
    target = os.environ.get("GITHUB_ENV")
    if not target:
        for key, value in lines.items():
            print(f"{key}={value}")
        return
    with open(target, "a", encoding="utf-8") as fh:
        for key, value in lines.items():
            fh.write(f"{key}={value}\n")


def _summary(text: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main() -> int:
    env = dict(os.environ)
    state, missing = classify(env)
    ref = env.get("RELEASE_REF", "")

    if state == "off":
        print(
            "::notice title=Windows binaries are not code signed::No Artifact Signing secrets are set, "
            "so the launcher, the sidecar and everything it unpacks ship unsigned and Smart App Control "
            "blocks them. See docs/desktop/WINDOWS_SIGNING.md."
        )
        _summary("Windows code signing (Artifact Signing): SKIPPED, no secrets set")
        _write_env({"WINDOWS_SIGNING": "off"})
        return 0
    if state == "partial":
        print(
            f"::error title=Windows signing is half configured::{len(missing)} of {len(REQUIRED)} "
            f"secrets are missing: {', '.join(missing)}. Set them, or clear all to ship unsigned deliberately."
        )
        return 1
    if not is_release_ref(ref):
        print(f"::notice title=Not signing a non-release build::{ref or '(no ref)'} is not a version tag.")
        _summary(f"Windows code signing: SKIPPED, `{ref}` is not a version tag")
        _write_env({"WINDOWS_SIGNING": "off"})
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from sign_windows_binaries import find_signtool

    signtool = find_signtool()
    if signtool is None:
        print("::error title=signtool was not found::Artifact Signing needs the Windows SDK signtool.exe.")
        return 1

    work = Path(os.environ.get("RUNNER_TEMP") or ".") / "artifact-signing"
    work.mkdir(parents=True, exist_ok=True)
    dlib = _fetch_dlib(work / "client")
    meta_path = work / "metadata.json"
    meta_path.write_text(json.dumps(metadata(env), indent=2), encoding="utf-8")

    # Forward slashes: these strings travel through tauri-action's argument
    # splitter and a JSON config, and neither needs to reason about backslashes.
    argv = sign_argv(signtool.replace("\\", "/"), str(dlib).replace("\\", "/"), str(meta_path).replace("\\", "/"))
    conf_path = work / "tauri.signing.conf.json"
    conf_path.write_text(json.dumps(tauri_config(argv), indent=2), encoding="utf-8")

    _write_env(
        {
            "WINDOWS_SIGNING": "on",
            "WINDOWS_SIGN_COMMAND": json.dumps(argv),
            "TAURI_SIGN_ARGS": "--config " + str(conf_path).replace("\\", "/"),
        }
    )
    _summary(f"Windows code signing: running against Artifact Signing for `{ref}`")
    print(f"Signing is configured for {ref}: {signtool} with {DLIB_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
