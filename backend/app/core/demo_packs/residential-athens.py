# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: greece-gr - Apartment Building, Athens
# ---------------------------------------------------------------------------
# A πολυκατοικία, the reinforced concrete apartment block on pilotis that
# makes up most of the Athenian housing stock, on a plot in Chalandri.
#
# Every line carries its ΝΕΤ article under the ``net`` key next to its DIN 276
# cost group. Articles with the plain ΟΙΚ prefix are ones whose number and
# description were read in a published 2025 municipal budget; ΝΑΟΙΚ and ΝΑΗΛΜ
# mark a new article (νέο άρθρο) written for the job in the chapter it belongs
# to, which is how a Greek budget prices work the lists do not cover. Unit
# prices are Athens 2026 levels in EUR excluding ΦΠΑ and excluding ΓΕ&ΟΕ,
# which the cascade adds.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-athens",
    project_name="Πολυκατοικία 20 διαμερισμάτων - Χαλάνδρι (Apartment Building, Athens)",
    project_description=(
        "Νέα πολυκατοικία με υπόγειο, πυλωτή και πέντε ορόφους στο Χαλάνδρι "
        "Αττικής, 20 διαμερίσματα, περίπου 2 400 m2 δομημένη επιφάνεια, "
        "φέρων οργανισμός από οπλισμένο σκυρόδεμα, ενεργειακή κατηγορία Α+. "
        "New apartment building in Chalandri, Athens: basement, pilotis and "
        "five storeys, 20 flats, approx. 2,400 m2 GFA, reinforced concrete "
        "frame, energy class A+. Priced at Athens 2026 levels in EUR "
        "excluding VAT."
    ),
    region="GR",
    classification_standard="din276",
    currency="EUR",
    locale="el",
    address={
        "street": "Οδός Αγίου Γεωργίου 14",
        "city": "Χαλάνδρι",
        "postcode": "152 34",
        "country": "Greece",
        "lat": 38.0215,
        "lng": 23.7990,
    },
    validation_rule_sets=["greece", "din276", "boq_quality"],
    boq_name="Προϋπολογισμός - Πολυκατοικία Χαλανδρίου (Budget)",
    boq_description=(
        "Προϋπολογισμός κατά άρθρα των Νέων Ενιαίων Τιμολογίων (ΝΕΤ ΟΙΚ, ΗΛΜ) "
        "και νέα άρθρα, ταξινομημένα κατά DIN 276. Τιμές Αθήνας 2026 σε EUR, "
        "χωρίς ΦΠΑ."
    ),
    boq_metadata={
        "standard": "ΝΕΤ (ΦΕΚ Β 1746/2017) / DIN 276",
        "phase": "Προϋπολογισμός μελέτης (Design budget)",
        "base_date": "2026-Q3",
        "price_level": "Αθήνα 2026 (EUR, χωρίς ΦΠΑ)",
    },
    sections=[
        (
            "20",
            "20-23 - Καθαιρέσεις και χωματουργικά (Demolition and earthworks)",
            {"din276": "310", "net": "ΟΙΚ 20.05.01"},
            [
                ("20.01", "Καθαίρεση υφιστάμενης μονοκατοικίας (Demolish existing house)", "lsum", 1, 28000, {"din276": "212", "net": "ΝΑΟΙΚ 22.02"}),
                ("20.02", "Γενική εκσκαφή υπογείου (Basement excavation)", "m3", 3200, 19.0, {"din276": "311", "net": "ΟΙΚ 20.05.01"}),
                ("20.03", "Επανεπίχωση με προϊόντα εκσκαφής (Backfill with excavated material)", "m3", 900, 12.0, {"din276": "311", "net": "ΝΑΟΙΚ 20.40"}),
                ("20.04", "Φόρτωση και μεταφορά προϊόντων εκσκαφής (Load and cart away spoil)", "m3", 2300, 9.0, {"din276": "311", "net": "ΝΑΟΙΚ 10.07"}),
            ],
        ),
        (
            "32",
            "32-38 - Σκυροδέματα, ξυλότυποι και οπλισμός (Concrete, formwork and reinforcement)",
            {"din276": "350", "net": "ΟΙΚ 32.01.06"},
            [
                ("32.01", "Σκυρόδεμα καθαριότητας C12/15 (Blinding concrete)", "m3", 60, 88.0, {"din276": "322", "net": "ΝΑΟΙΚ 32.01.02"}),
                ("32.02", "Σκυρόδεμα C25/30 θεμελίωσης, γενική κοιτόστρωση (Raft foundation)", "m3", 420, 108.0, {"din276": "322", "net": "ΟΙΚ 32.01.06"}),
                ("32.03", "Σκυρόδεμα C25/30 τοιχωμάτων υπογείου (Basement walls)", "m3", 180, 108.0, {"din276": "331", "net": "ΟΙΚ 32.01.06"}),
                ("32.04", "Σκυρόδεμα C25/30 υποστυλωμάτων και τοιχωμάτων (Columns and shear walls)", "m3", 340, 108.0, {"din276": "343", "net": "ΟΙΚ 32.01.06"}),
                ("32.05", "Σκυρόδεμα C25/30 πλακών και δοκών (Slabs and beams)", "m3", 710, 108.0, {"din276": "351", "net": "ΟΙΚ 32.01.06"}),
                ("32.06", "Ξυλότυποι θεμελίωσης (Foundation formwork)", "m2", 900, 16.5, {"din276": "322", "net": "ΟΙΚ 38.03"}),
                ("32.07", "Ξυλότυποι ανωδομής (Superstructure formwork)", "m2", 7800, 16.5, {"din276": "351", "net": "ΟΙΚ 38.03"}),
                ("32.08", "Χάλυβας οπλισμού B500C θεμελίωσης (Foundation reinforcement)", "kg", 55000, 1.15, {"din276": "322", "net": "ΟΙΚ 38.20.02"}),
                ("32.09", "Χάλυβας οπλισμού B500C ανωδομής (Superstructure reinforcement)", "kg", 120000, 1.15, {"din276": "351", "net": "ΟΙΚ 38.20.02"}),
                ("32.10", "Στεγάνωση υπογείου με ασφαλτικές μεμβράνες (Basement waterproofing)", "m2", 900, 22.0, {"din276": "325", "net": "ΝΑΟΙΚ 79.08"}),
            ],
        ),
        (
            "46",
            "46-79 - Τοιχοποιίες, κουφώματα και επιχρίσματα (Masonry, openings and finishes)",
            {"din276": "340", "net": "ΟΙΚ 46.01.03"},
            [
                ("46.01", "Μπατική τοιχοποιία εξωτερικών τοίχων (One-brick external walls)", "m2", 2100, 35.0, {"din276": "332", "net": "ΟΙΚ 46.01.03"}),
                ("46.02", "Δρομική τοιχοποιία εσωτερικών τοίχων (Half-brick internal walls)", "m2", 3900, 20.5, {"din276": "342", "net": "ΟΙΚ 46.01.02"}),
                ("46.03", "Σύστημα εξωτερικής θερμομόνωσης ETICS 10 cm (External insulation system)", "m2", 2100, 52.0, {"din276": "335", "net": "ΝΑΟΙΚ 79.49"}),
                ("46.04", "Κουφώματα αλουμινίου με θερμοδιακοπή και διπλούς υαλοπίνακες (Thermally broken aluminium windows)", "m2", 560, 290.0, {"din276": "334", "net": "ΝΑΟΙΚ 65.10"}),
                ("46.05", "Κιγκλιδώματα εξωστών από αλουμίνιο και γυαλί (Balcony balustrades)", "m", 420, 135.0, {"din276": "339", "net": "ΝΑΟΙΚ 64.10"}),
                ("46.06", "Θύρες εισόδου ασφαλείας διαμερισμάτων (Flat entrance security doors)", "pcs", 20, 850.0, {"din276": "344", "net": "ΝΑΟΙΚ 62.20"}),
                ("46.07", "Εσωτερικές ξύλινες θύρες (Internal timber doors)", "pcs", 110, 320.0, {"din276": "344", "net": "ΝΑΟΙΚ 54.20"}),
                ("46.08", "Επιχρίσματα τριπτά εσωτερικά (Three-coat internal plaster)", "m2", 13500, 15.0, {"din276": "345", "net": "ΟΙΚ 71.22"}),
                ("46.09", "Τσιμεντοκονία δαπέδων με θερμομόνωση (Insulated floor screed)", "m2", 2000, 14.0, {"din276": "352", "net": "ΝΑΟΙΚ 73.16"}),
                ("46.10", "Πλακίδια δαπέδων (Floor tiles)", "m2", 1700, 38.0, {"din276": "352", "net": "ΟΙΚ 73.33.03"}),
                ("46.11", "Πλακίδια τοίχων λουτρών και κουζινών (Wall tiles)", "m2", 900, 38.0, {"din276": "345", "net": "ΟΙΚ 73.34.02"}),
                ("46.12", "Μαρμάρινες επενδύσεις κλιμακοστασίου και εισόδου (Marble to stair and lobby)", "m2", 260, 95.0, {"din276": "352", "net": "ΝΑΟΙΚ 74.10"}),
                ("46.13", "Χρωματισμοί πλαστικοί σε δύο στρώσεις (Two-coat emulsion paint)", "m2", 13500, 7.0, {"din276": "345", "net": "ΝΑΟΙΚ 77.55"}),
                ("46.14", "Θερμομόνωση και στεγάνωση δώματος (Insulated and waterproofed flat roof)", "m2", 420, 48.0, {"din276": "363", "net": "ΝΑΟΙΚ 79.12"}),
            ],
        ),
        (
            "80",
            "ΗΛΜ - Ηλεκτρομηχανολογικές εγκαταστάσεις (Building services)",
            {"din276": "400", "net": "ΝΑΗΛΜ 1"},
            [
                ("80.01", "Ύδρευση και αποχέτευση ανά διαμέρισμα (Water and drainage per flat)", "pcs", 20, 7800.0, {"din276": "412", "net": "ΝΑΗΛΜ 8"}),
                ("80.02", "Είδη υγιεινής (Sanitary fittings)", "pcs", 20, 3200.0, {"din276": "412", "net": "ΝΑΗΛΜ 9"}),
                ("80.03", "Αντλίες θερμότητας αέρα-νερού ανά διαμέρισμα (Air-to-water heat pump per flat)", "pcs", 20, 7500.0, {"din276": "421", "net": "ΝΑΗΛΜ 41"}),
                ("80.04", "Ενδοδαπέδια θέρμανση (Underfloor heating)", "m2", 1850, 38.0, {"din276": "422", "net": "ΝΑΗΛΜ 42"}),
                ("80.05", "Ηλιακοί θερμοσίφωνες (Solar water heaters)", "pcs", 20, 1300.0, {"din276": "421", "net": "ΝΑΗΛΜ 43"}),
                ("80.06", "Ηλεκτρική εγκατάσταση ανά διαμέρισμα (Electrical installation per flat)", "pcs", 20, 6500.0, {"din276": "444", "net": "ΝΑΗΛΜ 60"}),
                ("80.07", "Φωτοβολταϊκό κοινοχρήστων 10 kWp (Common area photovoltaic system)", "lsum", 1, 16000.0, {"din276": "442", "net": "ΝΑΗΛΜ 65"}),
                ("80.08", "Ανελκυστήρας 630 kg, 7 στάσεις (Passenger lift, 7 stops)", "pcs", 1, 42000.0, {"din276": "461", "net": "ΝΑΗΛΜ 70"}),
                ("80.09", "Πυρανίχνευση και πυρόσβεση υπογείου (Fire detection and basement fire fighting)", "lsum", 1, 18000.0, {"din276": "456", "net": "ΝΑΗΛΜ 80"}),
                ("80.10", "Συνδέσεις με δίκτυα ΔΕΔΔΗΕ και ΕΥΔΑΠ (Grid and water utility connections)", "lsum", 1, 24000.0, {"din276": "220", "net": "ΝΑΗΛΜ 90"}),
            ],
        ),
        (
            "61",
            "61-79 - Συμπληρωματικές οικοδομικές εργασίες (Complementary building works)",
            {"din276": "330", "net": "ΝΑΟΙΚ 61.20"},
            [
                ("61.01", "Μεταλλικό στέγαστρο εισόδου (Steel entrance canopy)", "kg", 1200, 3.2, {"din276": "339", "net": "ΝΑΟΙΚ 61.20"}),
                ("61.02", "Γκαραζόπορτα υπογείου (Basement garage door)", "pcs", 1, 4800.0, {"din276": "334", "net": "ΝΑΟΙΚ 62.10"}),
                ("61.03", "Υαλοπίνακες ασφαλείας κλιμακοστασίου (Safety glazing to stair)", "m2", 60, 95.0, {"din276": "334", "net": "ΝΑΟΙΚ 76.20"}),
                ("61.04", "Μαρμάρινες ποδιές παραθύρων (Marble window sills)", "m", 520, 28.0, {"din276": "334", "net": "ΝΑΟΙΚ 75.10"}),
                ("61.05", "Σοβατεπί (Skirting)", "m", 2200, 6.0, {"din276": "352", "net": "ΝΑΟΙΚ 73.20"}),
                ("61.06", "Εξωτερικά επιχρίσματα πιλοτής (External render to pilotis)", "m2", 450, 18.0, {"din276": "335", "net": "ΝΑΟΙΚ 71.40"}),
                ("61.07", "Ηχομόνωση δαπέδων (Impact sound insulation to floors)", "m2", 1850, 9.0, {"din276": "352", "net": "ΝΑΟΙΚ 79.20"}),
                ("61.08", "Φυτεύσεις ακάλυπτου χώρου (Planting to the open plot)", "m2", 280, 25.0, {"din276": "570", "net": "ΝΑΠΡΣ 1.10"}),
            ],
        ),
        (
            "81",
            "ΗΛΜ - Συμπληρωματικές εγκαταστάσεις (Complementary services)",
            {"din276": "400", "net": "ΝΑΗΛΜ 10"},
            [
                ("81.01", "Αποχέτευση ομβρίων (Rainwater drainage)", "lsum", 1, 9500.0, {"din276": "411", "net": "ΝΑΗΛΜ 10"}),
                ("81.02", "Αντλιοστάσιο λυμάτων υπογείου (Basement sewage pumping station)", "pcs", 1, 7500.0, {"din276": "411", "net": "ΝΑΗΛΜ 12"}),
                ("81.03", "Κλιματιστικά split ανά διαμέρισμα (Split air conditioning per flat)", "pcs", 20, 2400.0, {"din276": "433", "net": "ΝΑΗΛΜ 44"}),
                ("81.04", "Γενικός πίνακας και παροχές (Main switchboard and supplies)", "pcs", 1, 14000.0, {"din276": "443", "net": "ΝΑΗΛΜ 61"}),
                ("81.05", "Φωτισμός κοινοχρήστων και ασφαλείας (Common area and emergency lighting)", "lsum", 1, 8500.0, {"din276": "445", "net": "ΝΑΗΛΜ 62"}),
                ("81.06", "Θυροτηλεόραση και κεραίες (Video door entry and aerials)", "lsum", 1, 6500.0, {"din276": "451", "net": "ΝΑΗΛΜ 66"}),
                ("81.07", "Αντικεραυνική προστασία (Lightning protection)", "lsum", 1, 5200.0, {"din276": "446", "net": "ΝΑΗΛΜ 67"}),
                ("81.08", "Πυροσβεστήρες και φωτιστικά ασφαλείας (Extinguishers and exit signs)", "lsum", 1, 2800.0, {"din276": "456", "net": "ΝΑΗΛΜ 81"}),
            ],
        ),
        (
            "23",
            "23 - Εργοτάξιο και ικριώματα (Site set-up and scaffolding)",
            {"din276": "390", "net": "ΝΑΟΙΚ 23.10"},
            [
                ("23.01", "Μεταλλικά ικριώματα όψεων (Facade scaffolding)", "m2", 3600, 6.0, {"din276": "392", "net": "ΝΑΟΙΚ 23.10"}),
                ("23.02", "Εργοταξιακή εγκατάσταση, περίφραξη και φύλαξη (Site set-up, hoarding and security)", "month", 16, 3500.0, {"din276": "391", "net": "ΝΑΟΙΚ 23.90"}),
            ],
        ),
    ],
    markups=[
        ("ΓΕ & ΟΕ (General expenses and contractor profit)", 18.0, "overhead", "direct_cost"),
        ("Απρόβλεπτα (Contingency)", 15.0, "contingency", "cumulative"),
        ("ΦΠΑ 24% (VAT)", 24.0, "tax", "cumulative"),
    ],
    total_months=16,
    tender_name="Ανάθεση εργολαβίας - Πολυκατοικία Χαλανδρίου",
    tender_companies=[
        ("Αττική Δομική ΑΤΕ", "prosfores@attiki-domiki.example", 0.97),
        ("Υμηττός Κατασκευαστική ΕΠΕ", "tender@ymittos-kataskevastiki.example", 1.02),
        ("Πεντέλη Τεχνική ΑΕ", "info@penteli-techniki.example", 1.05),
    ],
    tender_packages=[
        (
            "Φέρων οργανισμός και οικοδομικές εργασίες (Structure and building works)",
            "Εκσκαφές, σκυροδέματα, τοιχοποιίες, κουφώματα και επιχρίσματα",
            "evaluating",
            [
                ("Αττική Δομική ΑΤΕ", "prosfores@attiki-domiki.example", 0.97),
                ("Υμηττός Κατασκευαστική ΕΠΕ", "tender@ymittos-kataskevastiki.example", 1.02),
                ("Πεντέλη Τεχνική ΑΕ", "info@penteli-techniki.example", 1.05),
            ],
        ),
        (
            "Ηλεκτρομηχανολογικά (Building services)",
            "Ύδρευση, αποχέτευση, θέρμανση, ηλεκτρολογικά και ανελκυστήρας",
            "draft",
            [
                ("Ηλεκτρομηχανική Αττικής ΕΠΕ", "prosfores@ilm-attikis.example", 1.00),
                ("Θερμοτεχνική Βορείων ΙΚΕ", "tender@thermotechniki.example", 1.04),
            ],
        ),
    ],
    project_metadata={
        "address": "Οδός Αγίου Γεωργίου 14, 152 34 Χαλάνδρι, Greece",
        "client": "Ιδιώτης κύριος του έργου, αντιπαροχή (private owner, land-for-flats agreement)",
        "architect": "Γραφείο Αρχιτεκτονικής Μελέτης Βορείων Προαστίων",
        "structural_engineer": "Στατικά Γραφεία Αττικής",
        "gfa_m2": 2400,
        "storeys_above": 6,
        "storeys_below": 1,
        "units": 20,
        "seismic_design": "Eurocode 8 with the Greek national annex, seismic zone I (Athens)",
        "energy_class": "A+ under ΚΕΝΑΚ",
        "construction_standards": [
            "Ν. 4067/2012 - Νέος Οικοδομικός Κανονισμός (ΝΟΚ)",
            "Ν. 4495/2017 - οικοδομικές άδειες (e-Άδειες)",
            "ΚΕΝΑΚ - Κανονισμός Ενεργειακής Απόδοσης Κτιρίων",
        ],
        "vat_note": "Οι τιμές μονάδας είναι χωρίς ΦΠΑ και χωρίς ΓΕ&ΟΕ. Ο ΦΠΑ 24% εφαρμόζεται στο σύνολο.",
    },
)
