# Bundled CAD/BIM converters (desktop installer)

This directory is bundled into the desktop app as a read-only Tauri resource.
The Windows release workflow downloads the small DDC IFC converter
(`IfcExporter.exe` plus its Qt runtime, about 30 MB) from the public repo
`datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN` and extracts it into
`ifc_windows/` here, before the Tauri build packages resources. That lets a
fresh Windows install convert `.ifc` files offline with no first-use download.

At runtime the Tauri shell sets `OE_BUNDLED_CONVERTERS_DIR` to this directory and
the backend resolver (`backend/app/modules/boq/cad_import.py:find_converter`)
prefers `OE_BUNDLED_CONVERTERS_DIR/<format>_windows/<Exporter>.exe` over a
download.

Only the IFC converter is bundled. The RVT converter is about 600 MB and stays
on demand. On non-Windows builds, and on Windows builds where the download step
was skipped, this directory ships empty and the backend keeps its normal
auto-download behaviour unchanged.

Layout the workflow produces here:

    ifc_windows/
      IfcExporter.exe
      <bundled Qt6 DLLs, platforms/, styles/, datadrivenlibs/ ...>

The converter binaries themselves are intentionally not committed to this repo.
