# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: greece-gr - Primary School, Thessaloniki
# ---------------------------------------------------------------------------
# A public work, and so the Greek budget in its statutory form: priced by ΝΕΤ
# article, then ΓΕ&ΟΕ at 18 percent (Ν. 4412/2016 art. 53 §7θ) and απρόβλεπτα
# at 15 percent, the rate art. 156 §3α sets for a work below the EU threshold.
# A new twelve-classroom primary school with a gym hall for a municipality in
# the east of the city.
#
# ΟΙΚ articles were read in a published 2025 municipal budget; ΝΑΟΙΚ and ΝΑΗΛΜ
# mark a new article written for the job in the chapter it belongs to. Unit
# prices are Thessaloniki 2026 levels in EUR excluding ΦΠΑ and ΓΕ&ΟΕ.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="school-thessaloniki",
    project_name="Ανέγερση 12θέσιου Δημοτικού Σχολείου - Καλαμαριά (Primary School, Thessaloniki)",
    project_description=(
        "Ανέγερση νέου 12θέσιου δημοτικού σχολείου με κλειστό γυμναστήριο "
        "στην Καλαμαριά Θεσσαλονίκης, περίπου 3 200 m2, δύο όροφοι, "
        "κτίριο σχεδόν μηδενικής κατανάλωσης ενέργειας. Δημόσιο έργο κάτω "
        "από το ενωσιακό όριο. New twelve-classroom primary school with a "
        "gym hall in Kalamaria, Thessaloniki, approx. 3,200 m2 on two "
        "storeys, nearly zero-energy building. A public work below the EU "
        "threshold, priced at Thessaloniki 2026 levels in EUR excluding VAT."
    ),
    region="GR",
    classification_standard="din276",
    currency="EUR",
    locale="el",
    address={
        "street": "Οδός Κομνηνών 40",
        "city": "Καλαμαριά",
        "postcode": "551 33",
        "country": "Greece",
        "lat": 40.5838,
        "lng": 22.9540,
    },
    validation_rule_sets=["greece", "din276", "boq_quality"],
    boq_name="Προϋπολογισμός δημοπράτησης - Δημοτικό Σχολείο Καλαμαριάς (Tender budget)",
    boq_description=(
        "Προϋπολογισμός δημόσιου έργου κατά άρθρα ΝΕΤ ΟΙΚ και ΗΛΜ, με ΓΕ&ΟΕ "
        "18% και απρόβλεπτα 15% (Ν. 4412/2016), ταξινομημένος κατά DIN 276. "
        "Τιμές Θεσσαλονίκης 2026 σε EUR, χωρίς ΦΠΑ."
    ),
    boq_metadata={
        "standard": "ΝΕΤ (ΦΕΚ Β 1746/2017) / Ν. 4412/2016 / DIN 276",
        "phase": "Προϋπολογισμός δημοπράτησης (Pre-tender budget)",
        "base_date": "2026-Q3",
        "price_level": "Θεσσαλονίκη 2026 (EUR, χωρίς ΦΠΑ)",
    },
    sections=[
        (
            "20",
            "20 - Χωματουργικά (Earthworks)",
            {"din276": "310", "net": "ΟΙΚ 20.05.01"},
            [
                ("20.01", "Εκσκαφή θεμελίων σε έδαφος γαιώδες (Foundation excavation)", "m3", 2600, 18.5, {"din276": "311", "net": "ΟΙΚ 20.05.01"}),
                ("20.02", "Επιχώσεις με θραυστό υλικό λατομείου (Crushed stone fill)", "m3", 1400, 21.0, {"din276": "311", "net": "ΝΑΟΙΚ 20.30"}),
                ("20.03", "Φόρτωση και μεταφορά προϊόντων εκσκαφής (Load and cart away spoil)", "m3", 1900, 9.0, {"din276": "311", "net": "ΝΑΟΙΚ 10.07"}),
            ],
        ),
        (
            "32",
            "32-38 - Σκυροδέματα, ξυλότυποι και οπλισμός (Concrete, formwork and reinforcement)",
            {"din276": "350", "net": "ΟΙΚ 32.01.06"},
            [
                ("32.01", "Σκυρόδεμα καθαριότητας C12/15 (Blinding concrete)", "m3", 140, 88.0, {"din276": "322", "net": "ΝΑΟΙΚ 32.01.02"}),
                ("32.02", "Σκυρόδεμα C25/30 πεδιλοδοκών (Strip footings and ground beams)", "m3", 780, 106.0, {"din276": "322", "net": "ΟΙΚ 32.01.06"}),
                ("32.03", "Σκυρόδεμα C25/30 υποστυλωμάτων και τοιχωμάτων (Columns and shear walls)", "m3", 420, 106.0, {"din276": "343", "net": "ΟΙΚ 32.01.06"}),
                ("32.04", "Σκυρόδεμα C25/30 πλακών και δοκών (Slabs and beams)", "m3", 1150, 106.0, {"din276": "351", "net": "ΟΙΚ 32.01.06"}),
                ("32.05", "Ξυλότυποι θεμελίωσης (Foundation formwork)", "m2", 1900, 16.0, {"din276": "322", "net": "ΟΙΚ 38.03"}),
                ("32.06", "Ξυλότυποι ανωδομής (Superstructure formwork)", "m2", 9800, 16.0, {"din276": "351", "net": "ΟΙΚ 38.03"}),
                ("32.07", "Χάλυβας οπλισμού B500C θεμελίωσης (Foundation reinforcement)", "kg", 95000, 1.12, {"din276": "322", "net": "ΟΙΚ 38.20.02"}),
                ("32.08", "Χάλυβας οπλισμού B500C ανωδομής (Superstructure reinforcement)", "kg", 175000, 1.12, {"din276": "351", "net": "ΟΙΚ 38.20.02"}),
                ("32.09", "Μεταλλική στέγη γυμναστηρίου (Steel roof structure to gym hall)", "kg", 38000, 3.4, {"din276": "361", "net": "ΝΑΟΙΚ 61.30"}),
            ],
        ),
        (
            "46",
            "46-79 - Τοιχοποιίες, κουφώματα και επιχρίσματα (Masonry, openings and finishes)",
            {"din276": "340", "net": "ΟΙΚ 46.01.03"},
            [
                ("46.01", "Μπατική τοιχοποιία εξωτερικών τοίχων (One-brick external walls)", "m2", 2300, 34.0, {"din276": "332", "net": "ΟΙΚ 46.01.03"}),
                ("46.02", "Δρομική τοιχοποιία εσωτερικών τοίχων (Half-brick internal walls)", "m2", 3400, 20.0, {"din276": "342", "net": "ΟΙΚ 46.01.02"}),
                ("46.03", "Σύστημα εξωτερικής θερμομόνωσης ETICS 12 cm (External insulation system)", "m2", 2600, 54.0, {"din276": "335", "net": "ΝΑΟΙΚ 79.49"}),
                ("46.04", "Κουφώματα αλουμινίου με θερμοδιακοπή και ενεργειακούς υαλοπίνακες (Thermally broken aluminium windows)", "m2", 820, 285.0, {"din276": "334", "net": "ΝΑΟΙΚ 65.10"}),
                ("46.05", "Εξωτερικές σκίαστρες αλουμινίου (External aluminium sun louvres)", "m2", 420, 160.0, {"din276": "338", "net": "ΝΑΟΙΚ 65.40"}),
                ("46.06", "Θύρες αίθουσας διδασκαλίας (Classroom doors)", "pcs", 38, 520.0, {"din276": "344", "net": "ΝΑΟΙΚ 54.20"}),
                ("46.07", "Πυράντοχες θύρες εξόδων κινδύνου (Fire exit doors)", "pcs", 14, 1250.0, {"din276": "344", "net": "ΝΑΟΙΚ 62.30"}),
                ("46.08", "Επιχρίσματα τριπτά εσωτερικά (Three-coat internal plaster)", "m2", 12500, 14.5, {"din276": "345", "net": "ΟΙΚ 71.22"}),
                ("46.09", "Δάπεδα βινυλίου αιθουσών (Vinyl flooring to classrooms)", "m2", 1700, 34.0, {"din276": "352", "net": "ΝΑΟΙΚ 73.80"}),
                ("46.10", "Αθλητικό δάπεδο γυμναστηρίου (Sports floor to gym hall)", "m2", 620, 78.0, {"din276": "352", "net": "ΝΑΟΙΚ 73.85"}),
                ("46.11", "Πλακίδια δαπέδων διαδρόμων και WC (Floor tiles to corridors and toilets)", "m2", 900, 37.0, {"din276": "352", "net": "ΟΙΚ 73.33.03"}),
                ("46.12", "Πλακίδια τοίχων WC (Wall tiles to toilets)", "m2", 700, 37.0, {"din276": "345", "net": "ΟΙΚ 73.34.02"}),
                ("46.13", "Ψευδοροφές ορυκτών ινών ηχοαπορροφητικές (Acoustic mineral fibre ceilings)", "m2", 2600, 26.0, {"din276": "354", "net": "ΝΑΟΙΚ 78.60"}),
                ("46.14", "Χρωματισμοί ακρυλικοί (Acrylic paint)", "m2", 12500, 7.0, {"din276": "345", "net": "ΝΑΟΙΚ 77.55"}),
                ("46.15", "Θερμομόνωση και στεγάνωση δώματος (Insulated and waterproofed flat roof)", "m2", 1100, 48.0, {"din276": "363", "net": "ΝΑΟΙΚ 79.12"}),
                ("46.16", "Επικάλυψη στέγης γυμναστηρίου με θερμομονωτικά πάνελ (Insulated panel roof to gym hall)", "m2", 700, 58.0, {"din276": "363", "net": "ΝΑΟΙΚ 72.50"}),
                ("46.17", "Κιγκλιδώματα κλιμακοστασίων (Stair balustrades)", "m", 120, 145.0, {"din276": "359", "net": "ΝΑΟΙΚ 64.10"}),
            ],
        ),
        (
            "80",
            "ΗΛΜ - Ηλεκτρομηχανολογικές εγκαταστάσεις (Building services)",
            {"din276": "400", "net": "ΝΑΗΛΜ 1"},
            [
                ("80.01", "Ύδρευση, αποχέτευση και είδη υγιεινής (Plumbing, drainage and sanitary fittings)", "lsum", 1, 185000.0, {"din276": "412", "net": "ΝΑΗΛΜ 8"}),
                ("80.02", "Αντλίες θερμότητας και θερμαντικά σώματα (Heat pumps and heat emitters)", "lsum", 1, 265000.0, {"din276": "421", "net": "ΝΑΗΛΜ 41"}),
                ("80.03", "Μηχανικός αερισμός με ανάκτηση θερμότητας (Mechanical ventilation with heat recovery)", "m2", 3200, 42.0, {"din276": "431", "net": "ΝΑΗΛΜ 50"}),
                ("80.04", "Ισχυρά ρεύματα και φωτισμός LED (Power and LED lighting)", "m2", 3200, 48.0, {"din276": "444", "net": "ΝΑΗΛΜ 60"}),
                ("80.05", "Φωτοβολταϊκό σύστημα 50 kWp (Photovoltaic system)", "lsum", 1, 62000.0, {"din276": "442", "net": "ΝΑΗΛΜ 65"}),
                ("80.06", "Ασθενή ρεύματα, δομημένη καλωδίωση (Data cabling and low current)", "m2", 3200, 16.0, {"din276": "451", "net": "ΝΑΗΛΜ 66"}),
                ("80.07", "Ανελκυστήρας ΑμεΑ (Accessible lift)", "pcs", 1, 38000.0, {"din276": "461", "net": "ΝΑΗΛΜ 70"}),
                ("80.08", "Πυρανίχνευση και πυρόσβεση (Fire detection and fire fighting)", "m2", 3200, 18.0, {"din276": "456", "net": "ΝΑΗΛΜ 80"}),
                ("80.09", "Συνδέσεις με δίκτυα ΔΕΔΔΗΕ και ΕΥΑΘ (Grid and water utility connections)", "lsum", 1, 32000.0, {"din276": "220", "net": "ΝΑΗΛΜ 90"}),
            ],
        ),
        (
            "50",
            "Διαμόρφωση περιβάλλοντος χώρου (External works)",
            {"din276": "500", "net": "ΝΑΟΙΚ 41.10"},
            [
                ("50.01", "Πλακοστρώσεις αυλής με τσιμεντόπλακες (Concrete slab paving to playground)", "m2", 2400, 32.0, {"din276": "530", "net": "ΝΑΟΙΚ 41.10"}),
                ("50.02", "Περίφραξη με μεταλλικά κιγκλιδώματα (Boundary railings)", "m", 380, 95.0, {"din276": "530", "net": "ΝΑΟΙΚ 64.20"}),
                ("50.03", "Φυτεύσεις και άρδευση (Planting and irrigation)", "m2", 1500, 22.0, {"din276": "570", "net": "ΝΑΠΡΣ 1.10"}),
            ],
        ),
        (
            "61",
            "50-79 - Συμπληρωματικές οικοδομικές εργασίες (Complementary building works)",
            {"din276": "330", "net": "ΝΑΟΙΚ 50.10"},
            [
                ("61.01", "Μαρμάρινες ποδιές παραθύρων (Marble window sills)", "m", 600, 28.0, {"din276": "334", "net": "ΝΑΟΙΚ 75.10"}),
                ("61.02", "Σοβατεπί (Skirting)", "m", 2400, 6.0, {"din276": "352", "net": "ΝΑΟΙΚ 73.20"}),
                ("61.03", "Υαλοστάσια εισόδου (Entrance glazed screens)", "m2", 80, 320.0, {"din276": "334", "net": "ΝΑΟΙΚ 50.10"}),
                ("61.04", "Μεταλλικές θύρες λεβητοστασίου και αποθηκών (Steel doors to plant and stores)", "pcs", 8, 650.0, {"din276": "344", "net": "ΝΑΟΙΚ 62.10"}),
                ("61.05", "Ηχοαπορροφητικές επενδύσεις γυμναστηρίου (Acoustic lining to gym hall)", "m2", 700, 22.0, {"din276": "354", "net": "ΝΑΟΙΚ 79.20"}),
                ("61.06", "Εξωτερικά επιχρίσματα (External render)", "m2", 400, 18.0, {"din276": "335", "net": "ΝΑΟΙΚ 71.40"}),
                ("61.07", "Εξοπλισμός γυμναστηρίου (Gym hall equipment)", "lsum", 1, 35000.0, {"din276": "610", "net": "ΝΑΟΙΚ 61.90"}),
                ("61.08", "Δενδροφυτεύσεις αυλής (Tree planting to playground)", "pcs", 40, 180.0, {"din276": "570", "net": "ΝΑΠΡΣ 1.20"}),
            ],
        ),
        (
            "81",
            "ΗΛΜ - Συμπληρωματικές εγκαταστάσεις (Complementary services)",
            {"din276": "400", "net": "ΝΑΗΛΜ 10"},
            [
                ("81.01", "Αποχέτευση ομβρίων (Rainwater drainage)", "lsum", 1, 24000.0, {"din276": "411", "net": "ΝΑΗΛΜ 10"}),
                ("81.02", "Γενικός πίνακας χαμηλής τάσης (Main low-voltage switchboard)", "pcs", 1, 28000.0, {"din276": "443", "net": "ΝΑΗΛΜ 61"}),
                ("81.03", "Αντικεραυνική προστασία (Lightning protection)", "lsum", 1, 9000.0, {"din276": "446", "net": "ΝΑΗΛΜ 67"}),
                ("81.04", "Έλεγχος πρόσβασης και CCTV (Access control and CCTV)", "lsum", 1, 18000.0, {"din276": "456", "net": "ΝΑΗΛΜ 68"}),
                ("81.05", "Πυροσβεστήρες και φωτιστικά ασφαλείας (Extinguishers and exit signs)", "lsum", 1, 7500.0, {"din276": "456", "net": "ΝΑΗΛΜ 81"}),
            ],
        ),
        (
            "23",
            "23 - Εργοτάξιο και ικριώματα (Site set-up and scaffolding)",
            {"din276": "390", "net": "ΝΑΟΙΚ 23.10"},
            [
                ("23.01", "Μεταλλικά ικριώματα όψεων (Facade scaffolding)", "m2", 3000, 6.0, {"din276": "392", "net": "ΝΑΟΙΚ 23.10"}),
                ("23.02", "Εργοταξιακή εγκατάσταση, περίφραξη και πινακίδα έργου (Site set-up, hoarding and project board)", "month", 20, 3200.0, {"din276": "391", "net": "ΝΑΟΙΚ 23.90"}),
            ],
        ),
    ],
    markups=[
        ("ΓΕ & ΟΕ (General expenses and contractor profit)", 18.0, "overhead", "direct_cost"),
        ("Απρόβλεπτα (Contingency)", 15.0, "contingency", "cumulative"),
        ("ΦΠΑ 24% (VAT)", 24.0, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="Ανοικτή διαδικασία - Ανέγερση Δημοτικού Σχολείου Καλαμαριάς",
    tender_companies=[
        ("Θερμαϊκός Τεχνική ΑΤΕ", "prosfores@thermaikos-techniki.example", 0.94),
        ("Μακεδονική Δομή ΑΕ", "tender@makedoniki-domi.example", 0.99),
        ("Χαλκιδική Έργα ΕΠΕ", "info@chalkidiki-erga.example", 1.03),
    ],
    tender_packages=[
        (
            "Κύρια σύμβαση κατασκευής (Main works contract)",
            "Οικοδομικές και ηλεκτρομηχανολογικές εργασίες, με μέση έκπτωση ανά κατηγορία εργασιών",
            "evaluating",
            [
                ("Θερμαϊκός Τεχνική ΑΤΕ", "prosfores@thermaikos-techniki.example", 0.94),
                ("Μακεδονική Δομή ΑΕ", "tender@makedoniki-domi.example", 0.99),
                ("Χαλκιδική Έργα ΕΠΕ", "info@chalkidiki-erga.example", 1.03),
            ],
        ),
    ],
    project_metadata={
        "address": "Οδός Κομνηνών 40, 551 33 Καλαμαριά, Greece",
        "client": "Δήμος Καλαμαριάς (contracting authority)",
        "architect": "Τεχνικές Υπηρεσίες Δήμου Καλαμαριάς",
        "gfa_m2": 3200,
        "storeys_above": 2,
        "storeys_below": 0,
        "classrooms": 12,
        "procurement": "Ν. 4412/2016, open procedure, below the EU threshold",
        "seismic_design": "Eurocode 8 with the Greek national annex, importance class III (school)",
        "energy_class": "nearly zero-energy building under ΚΕΝΑΚ",
        "construction_standards": [
            "Ν. 4412/2016 - Δημόσιες Συμβάσεις Έργων",
            "ΦΕΚ Β 1746/2017 - Νέα Ενιαία Τιμολόγια (ΝΕΤ)",
            "ΚΕΝΑΚ - Κανονισμός Ενεργειακής Απόδοσης Κτιρίων",
        ],
        "vat_note": "Οι τιμές μονάδας είναι χωρίς ΦΠΑ και χωρίς ΓΕ&ΟΕ. Ο ΦΠΑ 24% εφαρμόζεται στο σύνολο.",
    },
)
