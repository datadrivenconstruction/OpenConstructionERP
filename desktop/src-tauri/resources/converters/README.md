# Bundled CAD/BIM converters (desktop installer)

This directory is bundled into the desktop app as a read-only Tauri resource.
The Windows release workflow downloads the DDC IFC converter, the
`DDC-IFC-to-Excel-0.3.1-preview-portable.zip` package of release `v2026.10.0` of
the public repo `datadrivenconstruction/cad2data-Revit-IFC-DWG`, checks its
SHA-256 against the digest pinned in the workflow and against the release's
`SHA256SUMS.txt`, and unpacks it into `ifc_windows/` here, before the Tauri build
packages resources. That lets a fresh Windows install convert `.ifc` files
offline with no first-use download.

At runtime the Tauri shell sets `OE_BUNDLED_CONVERTERS_DIR` to this directory and
the backend resolver (`backend/app/modules/boq/cad_import.py:find_converter`)
prefers `OE_BUNDLED_CONVERTERS_DIR/<format>_windows/<package layout>` over a
download.

Only the IFC converter is bundled. The RVT and DWG converters stay on demand. On
non-Windows builds, and on Windows builds where the download step was skipped,
this directory ships empty and the backend keeps its normal auto-download
behaviour unchanged.

The release carries no third-party CAD SDK. The package is a self-contained
Python application: its own CPython runtime, the DDC IFC reader and openpyxl.

Layout the workflow produces here:

    ifc_windows/
      runtime/python.exe          bundled CPython 3.13 runtime
      sources/ifc-excel/converter.py
      sources/ifc-independent/...
      .ddc-package.json           which release asset this folder came from

The converter is started as `runtime/python.exe sources/ifc-excel/converter.py
<input.ifc> --output <dir>` (see `backend/app/modules/boq/ddc_runner.py`).

The tag, asset name and digest in the workflow must stay equal to
`backend/app/core/converter_source.py`; `test_converter_ref_is_pinned.py` checks
that. The converter binaries themselves are intentionally not committed to this
repo.
