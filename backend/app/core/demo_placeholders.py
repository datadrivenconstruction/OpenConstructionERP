"""On-demand placeholder file generation for demo and mirror records.

Why this exists
---------------
Demo and showcase projects ship without the multi-megabyte binaries the
records reference (we do not bundle DWG/IFC/PDF blobs in the wheel), and
/files mirror documents can point at another module's upload whose blob
has been pruned. Rather than serve a raw 404 for those rows, the download
routes materialize a small but structurally valid file of the correct type
on first access, so every /files row downloads something openable.

Every writer here:

* writes only to a caller-supplied target path (the route is responsible
  for keeping that path inside a safe, owned directory),
* creates the parent directory if needed,
* produces a non-empty, type-correct file,
* degrades to a plain-text note if an optional library is unavailable.

The functions are intentionally dependency-light and synchronous; callers
run them off the event loop only if they are already in async context and
care about the (tiny) write latency.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions we can emit as a structurally valid CAD stub.
_DXF_LIKE_EXTS = frozenset({".dwg", ".dxf"})
_IFC_LIKE_EXTS = frozenset({".ifc", ".step", ".stp"})


def _ext_of(name: str) -> str:
    """Return the lowercased extension of ``name`` including the dot."""
    return Path(name).suffix.lower()


def write_pdf_placeholder(target: Path, title: str, note: str | None = None) -> None:
    """Write a minimal one-page PDF to ``target``.

    Falls back to a plain-text file (still at ``target``) when reportlab is
    not installed, so the caller always ends up with a real file.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.pdfgen import canvas as pdf_canvas  # type: ignore[import-untyped]

        from app.core.pdf_fonts import BODY_FONT, BOLD_FONT, register_pdf_fonts

        register_pdf_fonts()
        width, height = A4
        c = pdf_canvas.Canvas(str(target), pagesize=A4)
        c.setTitle(title)
        c.setFont(BOLD_FONT, 18)
        c.drawString(72, height - 90, title[:90])
        c.setFont(BODY_FONT, 11)
        c.drawString(72, height - 130, "Demo placeholder document")
        if note:
            c.drawString(72, height - 150, note[:90])
        c.setFont(BODY_FONT, 10)
        c.drawString(72, height - 200, "This file is auto-generated for the demo project.")
        c.drawString(72, height - 215, "Upload your own document to replace it.")
        c.setFont(BODY_FONT, 9)
        c.drawString(72, 60, "OpenConstructionERP - open-source construction cost platform")
        c.showPage()
        c.save()
    except Exception:  # pragma: no cover - reportlab missing or font failure
        logger.warning("reportlab unavailable; writing text placeholder for %s", target, exc_info=True)
        write_text_placeholder(target, title, note)


def write_dxf_placeholder(target: Path, title: str) -> None:
    """Write a minimal but structurally valid DXF document to ``target``.

    Used for ``.dwg`` and ``.dxf`` demo rows. A true binary DWG cannot be
    produced without a proprietary toolkit, so we emit ASCII DXF (a CAD
    interchange format every viewer reads) carrying a single text label.
    The file keeps its original extension so the /files row type is honest.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import ezdxf  # type: ignore[import-untyped]

        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()
        msp.add_text(
            title[:80] or "Demo drawing",
            dxfattribs={"height": 2.5, "insert": (0, 0)},
        )
        msp.add_text(
            "Auto-generated demo placeholder",
            dxfattribs={"height": 1.5, "insert": (0, -4)},
        )
        doc.saveas(str(target))
    except Exception:  # pragma: no cover - ezdxf missing
        logger.warning("ezdxf unavailable; writing minimal DXF text for %s", target, exc_info=True)
        target.write_text(_MINIMAL_DXF, encoding="ascii")


def write_ifc_placeholder(target: Path, title: str) -> None:
    """Write a minimal, schema-valid IFC (STEP) file to ``target``.

    The body is a hand-rolled IFC4 header plus a single IfcProject entity.
    No IfcOpenShell dependency - this is plain STEP text, which is exactly
    what an IFC file is on disk.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    safe_title = (title or "Demo model").replace("'", "")[:80]
    body = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION(('OpenConstructionERP demo placeholder'),'2;1');\n"
        f"FILE_NAME('{safe_title}','',(''),(''),'OpenConstructionERP','OpenConstructionERP','');\n"
        "FILE_SCHEMA(('IFC4'));\n"
        "ENDSEC;\n"
        "DATA;\n"
        "#1=IFCPROJECT('0demoplaceholder000000',$,'Demo placeholder',$,$,$,$,$,$);\n"
        "ENDSEC;\n"
        "END-ISO-10303-21;\n"
    )
    target.write_text(body, encoding="ascii")


def write_text_placeholder(target: Path, title: str, note: str | None = None) -> None:
    """Write a tiny UTF-8 text note to ``target`` as a last-resort fallback."""
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [title, "", "Demo placeholder file - auto-generated for the demo project."]
    if note:
        lines.append(note)
    lines.append("Upload your own file to replace it.")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_placeholder(target: Path, title: str, note: str | None = None) -> None:
    """Dispatch to the right placeholder writer based on ``target`` extension.

    ``.pdf`` -> PDF, ``.dwg``/``.dxf`` -> DXF, ``.ifc``/``.step``/``.stp`` ->
    IFC/STEP, anything else -> a small text note. The chosen type matches the
    file extension so the downloaded file is openable by the expected viewer.
    """
    ext = target.suffix.lower()
    if ext == ".pdf":
        write_pdf_placeholder(target, title, note)
    elif ext in _DXF_LIKE_EXTS:
        write_dxf_placeholder(target, title)
    elif ext in _IFC_LIKE_EXTS:
        write_ifc_placeholder(target, title)
    else:
        write_text_placeholder(target, title, note)


# A minimal valid ASCII DXF used only when ezdxf is not importable. It draws a
# single TEXT entity so the file is non-empty and parses in any DXF reader.
_MINIMAL_DXF = (
    "0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1024\n0\nENDSEC\n"
    "0\nSECTION\n2\nENTITIES\n"
    "0\nTEXT\n8\n0\n10\n0.0\n20\n0.0\n30\n0.0\n40\n2.5\n1\nDemo placeholder\n"
    "0\nENDSEC\n0\nEOF\n"
)
