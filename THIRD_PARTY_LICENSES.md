# Third-Party Licenses

This file is **auto-generated** by
[`.github/workflows/sbom-and-licenses.yml`](./.github/workflows/sbom-and-licenses.yml)
on each GitHub release. The latest generated inventory, along
with a CycloneDX Software Bill of Materials (SBOM) for both
backend (Python) and frontend (JavaScript/TypeScript), is
attached to the corresponding release as downloadable assets.

For the authoritative human-readable licensing overview —
including the dual-licensing model (AGPL-3.0-or-later /
commercial), third-party trademarks (Autodesk, Bentley,
buildingSMART, DIN, GAEB, NRM, CSI MasterFormat, ISO), and the
AI / cryptography / export-control notices — see
[`./NOTICE`](./NOTICE).

## Manual fallback

If you need the current list without waiting for a release:

```bash
# Backend
cd backend
pip install pip-licenses
pip-licenses --format=markdown

# Frontend
cd frontend
npm ci
npx license-checker --production --markdown
```

## Non-exhaustive summary (maintained manually in NOTICE)

See the **Third-Party Software** section of
[`./NOTICE`](./NOTICE) for the human-curated non-exhaustive list
of primary dependencies and their SPDX identifiers. The full
auto-generated inventory in this file supersedes the NOTICE list
in case of discrepancy for audit purposes.
