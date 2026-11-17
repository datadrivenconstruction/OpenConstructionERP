# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""LandXML 1.x surface reader (``Surfaces/Surface/Definition``, ``CgPoints``).

Files come from outside, so they are parsed with defusedxml (no DTD, no
entities, no external references), never the standard library parser. LandXML
writes a point as ``northing easting elevation``; this reader returns E, N, Z.
Only metric files are read: an imperial file is refused rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from defusedxml import ElementTree as SafeET

#: Linear units LandXML may declare that mean metres.
_METRIC = {"meter", "metre", "m", ""}


@dataclass
class LandXmlSurface:
    """One ``Surface``: vertices in E/N/Z and triangles as 0-based vertex indices."""

    name: str
    e: list[float] = field(default_factory=list)
    n: list[float] = field(default_factory=list)
    z: list[float] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class LandXmlFile:
    """What a LandXML file holds that the survey modules read."""

    surfaces: list[LandXmlSurface]
    cg_points: list[tuple[str, float, float, float | None, str]]
    epsg: int | None
    unit: str
    problems: list[str] = field(default_factory=list)


def _local(tag: Any) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _children(node: Any, name: str) -> list[Any]:
    return [c for c in list(node) if _local(c.tag) == name]


def _find(node: Any, name: str) -> Any | None:
    for c in node.iter():
        if _local(c.tag) == name:
            return c
    return None


def _nez(text: str | None) -> tuple[float, float, float | None] | None:
    parts = (text or "").replace(",", " ").split()
    if len(parts) < 2:
        return None
    try:
        n, e = float(parts[0]), float(parts[1])
        z = float(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return None
    return e, n, z


def parse_landxml(text: str) -> LandXmlFile:
    """Read surfaces and CgPoints from LandXML text.

    Raises:
        ValueError: when the text is not LandXML, is unsafe XML, or is not metric.
    """
    try:
        root = SafeET.fromstring(text.lstrip("﻿").encode("utf-8"), forbid_dtd=True)
    except Exception as exc:  # noqa: BLE001 - defusedxml raises several unrelated types
        raise ValueError(f"Not a readable LandXML file: {exc.__class__.__name__}") from exc
    if _local(root.tag) != "LandXML":
        raise ValueError("Not a LandXML file: the root element is not LandXML")

    unit = ""
    units = _find(root, "Units")
    if units is not None:
        for u in list(units):
            if _local(u.tag) == "Imperial":
                raise ValueError("Imperial LandXML is not read: export the surface in metres")
            if _local(u.tag) == "Metric":
                unit = str(u.get("linearUnit") or "meter").lower()
    if unit not in _METRIC:
        raise ValueError(f"LandXML linear unit {unit!r} is not metres")

    epsg: int | None = None
    cs = _find(root, "CoordinateSystem")
    if cs is not None:
        raw = cs.get("epsgCode") or cs.get("horizontalEPSG") or ""
        epsg = int(raw) if str(raw).strip().isdigit() else None

    problems: list[str] = []
    surfaces: list[LandXmlSurface] = []
    for block in [c for c in root.iter() if _local(c.tag) == "Surface"]:
        surf = LandXmlSurface(name=str(block.get("name") or f"Surface {len(surfaces) + 1}"))
        definition = _find(block, "Definition")
        if definition is None:
            problems.append(f"{surf.name}: no Definition")
            continue
        ids: dict[str, int] = {}
        pnts = _find(definition, "Pnts")
        for p in _children(pnts, "P") if pnts is not None else []:
            pos = _nez(p.text)
            if pos is None or pos[2] is None:
                problems.append(f"{surf.name}: point {p.get('id')} unreadable")
                continue
            ids[str(p.get("id") or len(ids) + 1)] = len(surf.e)
            surf.e.append(pos[0])
            surf.n.append(pos[1])
            surf.z.append(pos[2])  # type: ignore[arg-type]
        faces = _find(definition, "Faces")
        for f in _children(faces, "F") if faces is not None else []:
            if str(f.get("i") or "0") == "1":
                continue  # an invisible face: a hole in the surface
            refs = (f.text or "").split()
            if len(refs) < 3 or not all(r in ids for r in refs[:3]):
                problems.append(f"{surf.name}: face {f.text!r} names a missing point")
                continue
            surf.faces.append((ids[refs[0]], ids[refs[1]], ids[refs[2]]))
        if surf.e:
            surfaces.append(surf)

    cg: list[tuple[str, float, float, float | None, str]] = []
    for p in [c for c in root.iter() if _local(c.tag) == "CgPoint"]:
        pos = _nez(p.text)
        if pos is None:
            continue
        cg.append(
            (str(p.get("name") or p.get("pntRef") or len(cg) + 1), pos[0], pos[1], pos[2], str(p.get("code") or ""))
        )

    if not surfaces and not cg:
        raise ValueError("The LandXML file has no surface and no CgPoints")
    return LandXmlFile(surfaces=surfaces, cg_points=cg, epsg=epsg, unit=unit or "meter", problems=problems)


__all__ = ["LandXmlFile", "LandXmlSurface", "parse_landxml"]
