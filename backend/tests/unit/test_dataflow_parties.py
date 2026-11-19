"""Parties honeycomb: one hex per organisation, roles merged, monograms told apart."""

from app.modules.dataflow.parties import DELIVERY, _Collector, monogram, org_key


def test_same_company_through_three_sources_is_one_party() -> None:
    col = _Collector({})
    col.add("contact:a", "company", "Kurpfalz Kaeltetechnik GmbH", DELIVERY, "supplier", "oe_procurement")
    col.add("sub:b", "company", "KURPFALZ KAELTETECHNIK", DELIVERY, "subcontractor", "oe_subcontractors")
    col.add("bidder:c", "company", "kurpfalz kaeltetechnik", DELIVERY, "bidder", "oe_tendering")
    col.add("bidder:c", "company", "kurpfalz kaeltetechnik", DELIVERY, "bidder", "oe_tendering")
    parties = col.finish()
    names = [p.name for p in parties]
    assert len([n for n in names if org_key(n) == "kurpfalz kaeltetechnik"]) == 1
    merged = next(p for p in parties if p.id == "contact:a")
    assert merged.roles == ["supplier", "subcontractor", "bidder"]
    assert merged.touches["oe_tendering"] == 2
    assert merged.touches["oe_procurement"] == 1


def test_legal_form_and_punctuation_are_ignored() -> None:
    assert org_key("Odenwald Kälte- und Klimatechnik GmbH") == org_key("Odenwald Kälte und Klimatechnik")
    assert org_key("Demo Structures Ltd") == "demo structures"


def test_primary_role_follows_the_strongest_role() -> None:
    col = _Collector({})
    col.add("contact:x", "company", "Bohnenberger Bau", DELIVERY, "bidder", "oe_tendering")
    col.add("contact:x", "company", "Bohnenberger Bau", DELIVERY, "contractor", "oe_contracts")
    (party,) = col.finish()
    assert party.primary_role == "contractor"


def test_shared_initials_become_three_letters() -> None:
    col = _Collector({})
    col.add("c:1", "company", "Kurpfalz Kaeltetechnik GmbH", DELIVERY, "supplier", None)
    col.add("c:2", "company", "Kraichgau Klimabau GmbH", DELIVERY, "bidder", None)
    col.add("c:3", "company", "Elektro Wieblinger GmbH", DELIVERY, "bidder", None)
    by_id = {p.id: p.initials for p in col.finish()}
    assert by_id["c:1"] == "KUK"
    assert by_id["c:2"] == "KRK"
    assert by_id["c:3"] == "EW"


def test_monogram_skips_legal_words() -> None:
    assert monogram("Odenwald Kälte- und Klimatechnik GmbH", 3) == "OKK"
    assert monogram("Galabau GmbH", 2) == "GA"


def test_person_is_linked_to_the_company_on_the_roster() -> None:
    col = _Collector({})
    col.add("contact:s", "company", "Demo Structures Ltd", DELIVERY, "subcontractor", "oe_subcontractors")
    col.add("roster:1", "person", "Lena Vogt", DELIVERY, "site_manager", "oe_teams", org_name="Demo Structures")
    col.add("user:2", "person", "Anna Musterfrau", DELIVERY, "site_manager", "oe_teams")
    by_id = {p.id: p for p in col.finish()}
    assert by_id["roster:1"].org == "contact:s"
    assert by_id["roster:1"].primary_role == "person"
    assert by_id["user:2"].org is None
