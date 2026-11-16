# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# An IFC element may carry several IfcElementQuantity sets: a wall with a
# lintel's Qto_BeamBaseQuantities, or a standard Qto_* set beside a custom one.
# The bare names (Length, Volume) must come from the element's own base set,
# and every set stays readable under a set-qualified name (#565).

from __future__ import annotations

from app.modules.bim_hub.ifc_processor import _extract_quantities_for_element, _ifc_quantity_set_values


def test_flattened_row_takes_bare_names_from_the_elements_own_set():
    row = {
        "[qto_beambasequantities] length": 0.5,
        "[qto_beambasequantities] netvolume": 0.1,
        "[qto_wallbasequantities] length": 6.0,
        "[qto_wallbasequantities] netvolume": 1.8,
    }

    q = _ifc_quantity_set_values(row, "IfcWall")

    assert q["Length"] == 6.0
    assert q["Volume"] == 1.8
    assert q["qto_beambasequantities.Length"] == 0.5
    assert q["qto_wallbasequantities.Volume"] == 1.8


def test_flattened_row_prefers_a_base_set_over_a_custom_one():
    row = {"[custom_quantities] length": 9.0, "[qto_wallbasequantities] length": 6.0}

    q = _ifc_quantity_set_values(row, "")

    assert q["Length"] == 6.0
    assert q["custom_quantities.Length"] == 9.0


def test_single_set_keeps_the_old_shape():
    q = _ifc_quantity_set_values({"[qto_slabbasequantities] netvolume": 2.0}, "IfcSlab")

    assert q == {"Volume": 2.0}


def _step_entities() -> dict[int, dict]:
    def ent(kind: str, args: str) -> dict:
        import re

        return {"type": kind, "args_raw": args, "strings": re.findall(r"'([^']*)'", args)}

    return {
        10: ent("IFCWALL", "'0wall',#2,'Wall',$,$,#5,#6,'tag',$"),
        20: ent("IFCQUANTITYLENGTH", "'Length',$,$,6.0"),
        21: ent("IFCQUANTITYLENGTH", "'Length',$,$,0.5"),
        22: ent("IFCQUANTITYVOLUME", "'NetVolume',$,$,1.8"),
        30: ent("IFCELEMENTQUANTITY", "'0q1',#2,'Qto_WallBaseQuantities',$,$,(#20,#22)"),
        31: ent("IFCELEMENTQUANTITY", "'0q2',#2,'Qto_BeamBaseQuantities',$,$,(#21)"),
        40: ent("IFCRELDEFINESBYPROPERTIES", "'0r1',#2,$,$,(#10),#30"),
        41: ent("IFCRELDEFINESBYPROPERTIES", "'0r2',#2,$,$,(#10),#31"),
    }


def test_step_parser_keeps_the_wall_set_when_a_beam_set_follows():
    q = _extract_quantities_for_element(10, _step_entities())

    assert q["Length"] == 6.0
    assert q["NetVolume"] == 1.8
    assert q["Qto_BeamBaseQuantities.Length"] == 0.5
    assert q["Qto_WallBaseQuantities.Length"] == 6.0


def test_step_parser_single_set_has_only_bare_names():
    entities = _step_entities()
    del entities[41]

    assert _extract_quantities_for_element(10, entities) == {"Length": 6.0, "NetVolume": 1.8}
