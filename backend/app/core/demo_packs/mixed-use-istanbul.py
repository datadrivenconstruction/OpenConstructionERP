# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: turkey-birimfiyat - Mixed-use building, Istanbul Kagithane
# ---------------------------------------------------------------------------
# A Turkish estimate is a metraj (quantity take-off from the drawings) priced
# against birim fiyat, and the document the two produce is the kesif, summarised
# as a kesif ozeti. When the employer is a public body the same document is the
# yaklasik maliyet prepared under the Yapim Isleri Ihaleleri Uygulama
# Yonetmeligi before the tender is advertised. This bill follows that shape.
#
# There is no preliminaries or site-establishment section here, and that is not
# an omission. A Turkish kesif does not carry one. Site set-up, tower cranes,
# general scaffolding, insurance, site management and the contractor's own risk
# all sit inside the single "muteahhit kari ve genel giderler" head, which is
# why that head is a quarter of the works and not the ten to fifteen percent an
# overhead line carries in a bill written to a British or German convention.
#
# That 25 percent is one head. Turkish practice never splits it into overhead
# and profit, so the markup below is categorised as overhead. The consequence
# is worth knowing before someone reports it as a bug: the per-position price
# analysis renders an overhead line at 25 percent and no profit line at all,
# because that panel only draws the overhead, risk and profit rows that carry a
# non-zero percentage. It does not print a misleading zero. Splitting the head
# to fill that row would invent a division the country does not make.
#
# WHAT IS INDICATIVE HERE, PLAINLY.
#
# 1. The rates are market build-ups for Istanbul in 2026 lira, net of the
#    contractor's markup, which is what the 25 percent line then adds. They are
#    NOT extracts from the Ministry's published birim fiyat list. Take a rate
#    straight off that list instead and the 25 percent is already inside it, so
#    keeping the markup line as well double counts. That is the single most
#    likely way this bill gets misused, so it is said twice: once here and once
#    in project_metadata["markup_note"].
#
# 2. The lines carry the bill's own item numbers (özel poz, ÖZEL-1 to ÖZEL-84)
#    because no Ministry work-item book ships in this repository, and they are
#    to be replaced by the book's poz numbers once the price book is installed.
#    The sections carry no code. The lines used to carry codes in the
#    Ministry's XX.YYY.ZZZZ shape that were never taken from a published list:
#    most sat under first groups the unit-price book does not have, and a few
#    happened to be real numbers of unrelated resources. An own item claims no
#    more than point 1 already says, that the rate is this bill's own build-up.
#    A wrong number that looks precise is worse than an obvious gap.
#
# 3. Quantities are derived by ratio from the stated areas, not measured off
#    drawings. They hold the right order of magnitude and the right proportions
#    to each other. They are not a metraj and no one should treat them as one.
#
# 4. The seismic parameters in project_metadata are illustrative for a
#    Kagithane site. Real values come from the ground investigation and from the
#    AFAD hazard spectrum at the actual coordinates, and they move the
#    reinforcement and shear-wall quantities in section 02 materially. What is
#    not indicative is that TBDY 2018 governs the design: for an Istanbul
#    building the seismic requirements shape the structural system, the concrete
#    grade, the reinforcement ratio and even the anchorage of partitions,
#    ceilings and pipework, which is why they appear in the bill and not only in
#    a note.
#
# 5. Under Turkish inflation a lira total is meaningless without its date and
#    its index. The price level is stated once on the document, and a real
#    contract would carry fiyat farki adjustment against the TUIK Yi-UFE index
#    under the Yapim Isleri Fiyat Farki Esaslari. Neither the index series nor
#    the a and b coefficients are modelled in this template.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="mixed-use-istanbul",
    project_name="Karma Kullanımlı Bina - İstanbul, Kağıthane (Mixed-Use Building, Istanbul)",
    project_description=(
        "İstanbul Kağıthane, Cendere vadisinde 4.800 m2 arsa üzerinde karma kullanımlı "
        "bina yapımı. 2 bodrum, zemin ve 15 normal kat; yapı yüksekliği 52,30 m, toplam "
        "inşaat alanı yaklaşık 34.000 m2. Zemin ve 1. katta 3.000 m2 ticari alan, 2.-5. "
        "katlarda 6.000 m2 ofis, 6.-15. katlarda 120 daireli 15.400 m2 konut, iki bodrum "
        "katta 240 araçlık kapalı otopark ve teknik hacimler. Taşıyıcı sistem, TBDY 2018'e "
        "göre süneklik düzeyi yüksek betonarme perde ve çerçevelerden oluşan karma sistem; "
        "temel, jet grout ile iyileştirilmiş zemin üzerinde radye. Cephe, ticari ve ofis "
        "katlarında ısıcamlı giydirme cephe, konut katlarında alüminyum doğrama ve taşyünü "
        "mantolama. Metraj ve keşif, Çevre, Şehircilik ve İklim Değişikliği Bakanlığı birim "
        "fiyat ve rayiçleri esas alınarak 2026 İstanbul fiyat seviyesinde düzenlenmiştir. "
        "Kâr ve genel giderler ile KDV hariç imalat bedeli yaklaşık 1,28 milyar TL. "
        "New-build mixed-use building on a 4,800 m2 plot in the Cendere valley, "
        "Kagithane, Istanbul. Two basements, ground floor and 15 upper floors, building "
        "height 52.30 m, gross floor area approx. 34,000 m2: 3,000 m2 of retail at ground "
        "and first floor, 6,000 m2 of offices over four floors, 120 flats totalling "
        "15,400 m2 above, and 240 parking spaces plus plant across two basement levels. "
        "Cast in-situ reinforced concrete dual system of high-ductility shear walls and "
        "frames to TBDY 2018, on a raft over jet-grouted ground. Priced by quantity "
        "take-off against Ministry unit prices at Istanbul 2026 levels; measured works "
        "approx. TRY 1.28 billion before markup and VAT."
    ),
    region="TR",
    classification_standard="birimfiyat",
    currency="TRY",
    locale="tr",
    address={
        "street": "Merkez Mahallesi, Cendere Caddesi No: 42",
        "city": "İstanbul",
        "postcode": "34406",
        "country": "Turkey",
        "lat": 41.0918,
        "lng": 28.9684,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="Keşif Özeti - Bakanlık birim fiyatları 2026 (Bill of Quantities)",
    boq_description=(
        "Metraja dayalı keşif özeti. Birim fiyatlar Çevre, Şehircilik ve İklim Değişikliği "
        "Bakanlığı birim fiyat ve rayiçleri esas alınarak 2026 İstanbul piyasa seviyesinde "
        "oluşturulmuş olup, müteahhit kârı ve genel giderler ile KDV hariçtir. "
        "Quantity-based bill of quantities. Unit rates are built up to Istanbul 2026 market "
        "levels on the Ministry unit-price and resource-price basis, and exclude both the "
        "contractor's profit and overheads head and VAT."
    ),
    boq_metadata={
        "standard": "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı birim fiyatları (2026)",
        "phase": "Uygulama projesi - yaklaşık maliyet / keşif özeti (Tender-stage approximate cost)",
        "base_date": "2026-Q1",
        "price_level": "İstanbul 2026 (Istanbul 2026)",
        "pricing_method": "Metraj ve birim fiyat (quantity take-off against unit prices)",
    },
    sections=[
        (
            "01",
            "Bölüm 1. Kazı, iksa ve zemin işleri (Excavation, shoring and ground works)",
            {},
            [
                ("1.1", "Makine ile yumuşak ve sert toprak kazılması, yükleme dahil (Machine excavation, soft and hard soil, incl. loading)", "m3", 46_000.0, 240.0, {"birimfiyat": "ÖZEL-1"}),
                ("1.2", "Makine ile küskülük ve yumuşak kaya kazılması (Machine excavation, rippable and soft rock)", "m3", 8_000.0, 520.0, {"birimfiyat": "ÖZEL-2"}),
                ("1.3", "Kazı fazlası nakli ve döküm sahası bedeli, 25 km (Surplus spoil haulage and tipping, 25 km)", "m3", 58_000.0, 420.0, {"birimfiyat": "ÖZEL-3"}),
                ("1.4", "Fore kazık iksa perdesi, D=80 cm, C30/37 (Bored-pile shoring wall, 800 mm dia., C30/37)", "m", 3_000.0, 7_200.0, {"birimfiyat": "ÖZEL-4"}),
                ("1.5", "Öngermeli geçici zemin ankrajı, halatlı (Prestressed temporary ground anchor, strand)", "m", 2_160.0, 3_200.0, {"birimfiyat": "ÖZEL-5"}),
                ("1.6", "Jet grout ile zemin iyileştirmesi, D=60 cm (Ground improvement by jet grouting, 600 mm dia.)", "m", 6_400.0, 2_600.0, {"birimfiyat": "ÖZEL-6"}),
                ("1.7", "Temel altı drenaj, blokaj ve granüler dolgu (Sub-foundation drainage, hardcore and granular fill)", "m2", 5_000.0, 620.0, {"birimfiyat": "ÖZEL-7"}),
            ],
        ),
        (
            "02",
            "Bölüm 2. Betonarme taşıyıcı sistem, TBDY 2018 (Reinforced concrete structure to TBDY 2018)",
            {},
            [
                ("2.1", "Grobeton C16/20, temel altı (Blinding concrete C16/20 under foundations)", "m3", 520.0, 3_300.0, {"birimfiyat": "ÖZEL-8"}),
                ("2.2", "Radye temel betonu C30/37, kristalize su yalıtım katkılı (Raft foundation C30/37, crystalline waterproofing admixture)", "m3", 7_000.0, 4_350.0, {"birimfiyat": "ÖZEL-9"}),
                ("2.3", "Bodrum perde betonu C30/37 (Basement retaining-wall concrete C30/37)", "m3", 1_150.0, 4_450.0, {"birimfiyat": "ÖZEL-10"}),
                ("2.4", "Perde ve kolon betonu C35/45, süneklik düzeyi yüksek (Shear-wall and column concrete C35/45, high ductility)", "m3", 4_100.0, 4_650.0, {"birimfiyat": "ÖZEL-11"}),
                ("2.5", "Kiriş, döşeme ve merdiven betonu C30/37 (Beam, slab and stair concrete C30/37)", "m3", 7_850.0, 4_300.0, {"birimfiyat": "ÖZEL-12"}),
                ("2.6", "Nervürlü beton çeliği B420C, Ø8-12 mm, kesme, bükme ve yerine koyma (Ribbed bar B420C, 8-12 mm, cut, bent and fixed)", "ton", 985.0, 40_000.0, {"birimfiyat": "ÖZEL-13"}),
                ("2.7", "Nervürlü beton çeliği B420C, Ø14-32 mm, sarılma bölgesi etriyeleri dahil (Ribbed bar B420C, 14-32 mm, incl. confinement stirrups)", "ton", 1_610.0, 37_500.0, {"birimfiyat": "ÖZEL-14"}),
                ("2.8", "Perde ve kolon kalıbı, çelik çerçeveli plywood (Wall and column formwork, steel-framed plywood)", "m2", 34_000.0, 950.0, {"birimfiyat": "ÖZEL-15"}),
                ("2.9", "Kiriş, döşeme ve merdiven kalıbı, iskele ve destekleme dahil (Beam, slab and stair formwork, incl. falsework)", "m2", 64_200.0, 1_050.0, {"birimfiyat": "ÖZEL-16"}),
                ("2.10", "Deprem derzi profili ve yangın durdurucu dolgusu (Seismic movement-joint profile with fire-stop infill)", "m", 420.0, 3_800.0, {"birimfiyat": "ÖZEL-17"}),
                ("2.11", "Kimyasal ankraj ile donatı ekimi, Ø16-25 mm, perde ve kolon filizleri (Post-installed rebar dowels with chemical anchor, 16-25 mm)", "adet", 8_400.0, 480.0, {"birimfiyat": "ÖZEL-18"}),
                ("2.12", "Donatı mekanik ekleme manşonu, Ø20-32 mm, perde düşey donatısı (Mechanical rebar couplers, 20-32 mm, shear-wall verticals)", "adet", 6_100.0, 620.0, {"birimfiyat": "ÖZEL-19"}),
                ("2.13", "Su tutucu bant, radye ve perde soğuk derzlerinde (Waterstop to raft and wall construction joints)", "m", 1_850.0, 1_450.0, {"birimfiyat": "ÖZEL-20"}),
                ("2.14", "Döşeme tesisat boşlukları, şaft kalıbı ve geçiş kovanları (Slab service openings, shaft formwork and sleeves)", "adet", 4_200.0, 980.0, {"birimfiyat": "ÖZEL-21"}),
            ],
        ),
        (
            "03",
            "Bölüm 3. Duvar, yalıtım ve çatı işleri (Masonry, insulation and roofing)",
            {},
            [
                ("3.1", "Gazbeton blok duvar, 20 cm, dış ve ayırıcı duvarlar (AAC block wall, 200 mm, external and separating)", "m2", 12_000.0, 1_150.0, {"birimfiyat": "ÖZEL-22"}),
                ("3.2", "Gazbeton blok bölme duvar, 10 cm (AAC block partition, 100 mm)", "m2", 22_000.0, 780.0, {"birimfiyat": "ÖZEL-23"}),
                ("3.3", "Dolgu duvar hatılı, lento ve bağlantı elemanları, TBDY 2018 Bölüm 6 (Infill-wall ring beams, lintels and restraint ties, TBDY 2018 Section 6)", "m3", 620.0, 5_200.0, {"birimfiyat": "ÖZEL-24"}),
                ("3.4", "Alçı levha bölme duvar, ofis katları (Plasterboard partition on metal studs, office floors)", "m2", 6_500.0, 1_350.0, {"birimfiyat": "ÖZEL-25"}),
                ("3.5", "Temel ve bodrum perdesi su yalıtımı, koruma tabakası dahil (Raft and basement-wall tanking, incl. protection layer)", "m2", 7_850.0, 1_300.0, {"birimfiyat": "ÖZEL-26"}),
                ("3.6", "Islak hacim su yalıtımı, poliüretan esaslı (Wet-area waterproofing, polyurethane based)", "m2", 4_200.0, 780.0, {"birimfiyat": "ÖZEL-27"}),
                ("3.7", "Çatı su yalıtımı, ısı yalıtımı, eğim betonu ve koruma şapı (Roof waterproofing, insulation, screed to falls and protective topping)", "m2", 1_700.0, 2_450.0, {"birimfiyat": "ÖZEL-28"}),
                ("3.8", "Yangın dayanımlı şaft ve tesisat bacası duvarı, EI90 (Fire-rated shaft and services riser wall, EI90)", "m2", 3_800.0, 1_850.0, {"birimfiyat": "ÖZEL-29"}),
                ("3.9", "Zemine oturan döşeme altı ısı yalıtımı ve buhar kesici (Ground-bearing slab insulation and vapour barrier)", "m2", 4_600.0, 780.0, {"birimfiyat": "ÖZEL-30"}),
            ],
        ),
        (
            "04",
            "Bölüm 4. Cephe ve doğrama işleri (Facade and joinery)",
            {},
            [
                ("4.1", "Giydirme cephe, ısıcamlı Low-E, ticari ve ofis katları (Curtain wall, Low-E double glazing, retail and office floors)", "m2", 4_200.0, 13_500.0, {"birimfiyat": "ÖZEL-31"}),
                ("4.2", "Kompozit alüminyum panel cephe kaplaması (Aluminium composite panel cladding)", "m2", 3_600.0, 6_500.0, {"birimfiyat": "ÖZEL-32"}),
                ("4.3", "Dış cephe ısı yalıtımı, taşyünü 8 cm, TS 825 (External wall insulation, 80 mm mineral wool, TS 825)", "m2", 11_500.0, 1_900.0, {"birimfiyat": "ÖZEL-33"}),
                ("4.4", "Alüminyum ısı yalıtımlı doğrama, ısıcam, konut katları (Thermally broken aluminium windows, insulating glass, residential floors)", "m2", 4_800.0, 7_200.0, {"birimfiyat": "ÖZEL-34"}),
                ("4.5", "Cam balkon korkuluğu, lamine (Laminated glass balcony balustrade)", "m", 1_900.0, 4_800.0, {"birimfiyat": "ÖZEL-35"}),
                ("4.6", "Çelik daire giriş kapısı (Steel flat entrance door)", "adet", 120.0, 24_000.0, {"birimfiyat": "ÖZEL-36"}),
                ("4.7", "Yangına dayanıklı çelik kapı, EI60 (Fire-rated steel door, EI60)", "adet", 180.0, 19_500.0, {"birimfiyat": "ÖZEL-37"}),
                ("4.8", "Ahşap iç kapı, kasa ve donanım dahil (Timber internal door, incl. frame and hardware)", "adet", 640.0, 11_500.0, {"birimfiyat": "ÖZEL-38"}),
            ],
        ),
        (
            "05",
            "Bölüm 5. İnce yapı ve kaplama işleri (Finishes)",
            {},
            [
                ("5.1", "Makine ile alçı sıva (Machine-applied gypsum plaster)", "m2", 88_000.0, 420.0, {"birimfiyat": "ÖZEL-39"}),
                ("5.2", "Saten alçı perdah ve plastik boya, iki kat (Skim plaster and emulsion paint, two coats)", "m2", 92_000.0, 360.0, {"birimfiyat": "ÖZEL-40"}),
                ("5.3", "Tesviye şapı, 5 cm (Levelling screed, 50 mm)", "m2", 30_000.0, 520.0, {"birimfiyat": "ÖZEL-41"}),
                ("5.4", "Laminat parke, konut katları (Laminate flooring, residential floors)", "m2", 11_000.0, 1_900.0, {"birimfiyat": "ÖZEL-42"}),
                ("5.5", "Seramik zemin ve duvar kaplaması (Ceramic floor and wall tiling)", "m2", 18_000.0, 1_520.0, {"birimfiyat": "ÖZEL-43"}),
                ("5.6", "Doğal taş kaplama, giriş holü ve asansör holleri (Natural stone finish, entrance lobby and lift halls)", "m2", 1_400.0, 5_200.0, {"birimfiyat": "ÖZEL-44"}),
                ("5.7", "Karo halı, ofis katları (Carpet tile, office floors)", "m2", 4_500.0, 1_750.0, {"birimfiyat": "ÖZEL-45"}),
                ("5.8", "Alçı levha ve taşyünü asma tavan, sismik askı dahil (Plasterboard and mineral-fibre suspended ceiling, incl. seismic hangers)", "m2", 19_600.0, 1_390.0, {"birimfiyat": "ÖZEL-46"}),
                ("5.9", "Mutfak tezgâhı ve dolabı (Kitchen worktop and units)", "takım", 120.0, 68_000.0, {"birimfiyat": "ÖZEL-47"}),
                ("5.10", "Mermer denizlik, harpuşta ve kapı eşiği (Marble window sills, parapet copings and door thresholds)", "m", 4_100.0, 1_850.0, {"birimfiyat": "ÖZEL-48"}),
                ("5.11", "Merdiven basamak ve rıht kaplaması, doğal taş (Natural stone stair treads and risers)", "m2", 1_600.0, 4_800.0, {"birimfiyat": "ÖZEL-49"}),
                ("5.12", "Paslanmaz çelik korkuluk ve küpeşte, merdiven ve sahanlıklar (Stainless steel balustrade and handrail, stairs and landings)", "m", 1_450.0, 5_600.0, {"birimfiyat": "ÖZEL-50"}),
            ],
        ),
        (
            "06",
            "Bölüm 6. Mekanik tesisat (Mechanical installations)",
            {},
            [
                ("6.1", "Temiz su, pis su ve yağmur suyu tesisatı (Domestic water, foul and rainwater pipework)", "m", 19_500.0, 600.0, {"birimfiyat": "ÖZEL-51"}),
                ("6.2", "Vitrifiye ve batarya montajı (Sanitaryware and tapware installation)", "takım", 320.0, 38_000.0, {"birimfiyat": "ÖZEL-52"}),
                ("6.3", "Yoğuşmalı kombi ve panel radyatör tesisatı, daire başına (Condensing boiler and panel radiators, per flat)", "takım", 120.0, 112_000.0, {"birimfiyat": "ÖZEL-53"}),
                ("6.4", "Doğalgaz kolon hattı ve daire içi tesisatı (Gas riser and in-flat pipework)", "m", 3_200.0, 950.0, {"birimfiyat": "ÖZEL-54"}),
                ("6.5", "VRF iklimlendirme sistemi, ofis ve ticari alanlar (VRF air-conditioning system, office and retail areas)", "m2", 9_000.0, 6_500.0, {"birimfiyat": "ÖZEL-55"}),
                ("6.6", "Galvaniz sac hava kanalı ve menfezler (Galvanised steel ductwork and grilles)", "m2", 14_000.0, 1_850.0, {"birimfiyat": "ÖZEL-56"}),
                ("6.7", "Otopark jet fanlı duman tahliyesi ve merdiven basınçlandırması (Car park jet-fan smoke extract and stair pressurisation)", "takım", 1.0, 24_300_000.0, {"birimfiyat": "ÖZEL-57"}),
                ("6.8", "Yağmurlama (sprinkler) sistemi (Automatic sprinkler system)", "m2", 24_000.0, 1_150.0, {"birimfiyat": "ÖZEL-58"}),
                ("6.9", "Yangın dolabı, hidrant ve yangın pompa grubu (Hose reels, hydrants and fire pump set)", "takım", 1.0, 15_300_000.0, {"birimfiyat": "ÖZEL-59"}),
                ("6.10", "Hidrofor, su depoları ve basınçlandırma grubu (Booster set, water tanks and pressurisation)", "takım", 1.0, 7_200_000.0, {"birimfiyat": "ÖZEL-60"}),
                ("6.11", "Mekanik tesisat sismik askı ve destek sistemleri, TBDY 2018 Bölüm 6 (Seismic restraint of mechanical services, TBDY 2018 Section 6)", "m", 6_500.0, 1_250.0, {"birimfiyat": "ÖZEL-61"}),
                ("6.12", "Otopark karbonmonoksit gaz algılama ve havalandırma kumandası (Car park carbon-monoxide detection and ventilation control)", "m2", 9_600.0, 320.0, {"birimfiyat": "ÖZEL-62"}),
                ("6.13", "Bodrum drenaj ve atık su terfi istasyonu (Basement drainage and foul-water lifting station)", "takım", 1.0, 4_850_000.0, {"birimfiyat": "ÖZEL-63"}),
            ],
        ),
        (
            "07",
            "Bölüm 7. Elektrik ve zayıf akım tesisatı (Electrical and ELV installations)",
            {},
            [
                ("7.1", "OG hücreleri ve 2x1600 kVA kuru tip trafo (MV switchgear and 2 x 1600 kVA dry-type transformers)", "takım", 1.0, 26_000_000.0, {"birimfiyat": "ÖZEL-64"}),
                ("7.2", "AG dağıtım panoları ve kompanzasyon tesisi (LV distribution boards and power-factor correction)", "takım", 1.0, 18_500_000.0, {"birimfiyat": "ÖZEL-65"}),
                ("7.3", "Dizel jeneratör, 800 kVA, otomatik transfer dahil (Diesel generator, 800 kVA, incl. automatic transfer)", "adet", 1.0, 9_600_000.0, {"birimfiyat": "ÖZEL-66"}),
                ("7.4", "Halojensiz enerji kablosu ve kablo taşıma sistemleri (Halogen-free power cable and containment)", "m", 62_000.0, 275.0, {"birimfiyat": "ÖZEL-67"}),
                ("7.5", "LED aydınlatma armatürü, acil aydınlatma ve yönlendirme dahil (LED luminaires, incl. emergency and exit signage)", "adet", 7_650.0, 2_310.0, {"birimfiyat": "ÖZEL-68"}),
                ("7.6", "Daire ve mahal panoları, priz ve anahtar tesisatı (Flat and zone boards, sockets and switching)", "adet", 148.0, 18_000.0, {"birimfiyat": "ÖZEL-69"}),
                ("7.7", "Adresli yangın algılama ve sesli uyarı sistemi (Addressable fire detection and voice alarm)", "m2", 34_000.0, 480.0, {"birimfiyat": "ÖZEL-70"}),
                ("7.8", "Zayıf akım sistemleri; diafon, kamera, geçiş kontrol ve veri (ELV systems: entry phone, CCTV, access control and data)", "takım", 1.0, 22_000_000.0, {"birimfiyat": "ÖZEL-71"}),
                ("7.9", "Paratoner ve topraklama tesisatı (Lightning protection and earthing)", "takım", 1.0, 3_800_000.0, {"birimfiyat": "ÖZEL-72"}),
                ("7.10", "Elektrikli araç şarj ünitesi, otopark (Electric-vehicle charging units, car park)", "adet", 24.0, 145_000.0, {"birimfiyat": "ÖZEL-73"}),
                ("7.11", "Bina otomasyon sistemi, BMS (Building management system)", "takım", 1.0, 9_800_000.0, {"birimfiyat": "ÖZEL-74"}),
                ("7.12", "Çatı üstü fotovoltaik güneş enerjisi sistemi, BEP Yönetmeliği yenilenebilir enerji payı (Rooftop photovoltaic array, BEP renewable-energy share)", "kWp", 120.0, 42_000.0, {"birimfiyat": "ÖZEL-75"}),
            ],
        ),
        (
            "08",
            "Bölüm 8. Asansör, otopark ve çevre düzenlemesi (Lifts, car park and external works)",
            {},
            [
                ("8.1", "Yolcu asansörü, 13 kişilik, 18 durak (Passenger lift, 13 person, 18 stops)", "adet", 6.0, 4_200_000.0, {"birimfiyat": "ÖZEL-76"}),
                ("8.2", "Yangın asansörü, 18 durak, jeneratör beslemeli (Firefighting lift, 18 stops, generator backed)", "adet", 2.0, 5_400_000.0, {"birimfiyat": "ÖZEL-77"}),
                ("8.3", "Yürüyen merdiven, ticari katlar (Escalator, retail floors)", "adet", 2.0, 2_600_000.0, {"birimfiyat": "ÖZEL-78"}),
                ("8.4", "Otopark epoksi zemin kaplaması ve çizgi işleri (Car park epoxy floor coating and line marking)", "m2", 9_000.0, 1_520.0, {"birimfiyat": "ÖZEL-79"}),
                ("8.5", "Otopark bariyeri, yönlendirme ve plaka tanıma sistemi (Car park barrier, wayfinding and plate recognition)", "takım", 1.0, 2_400_000.0, {"birimfiyat": "ÖZEL-80"}),
                ("8.6", "Peyzaj, bitkilendirme, otomatik sulama ve sert zemin kaplamaları (Landscaping, planting, irrigation and hard paving)", "m2", 4_000.0, 2_500.0, {"birimfiyat": "ÖZEL-81"}),
                ("8.7", "Betonarme istinat duvarı (Reinforced concrete retaining wall)", "m3", 340.0, 6_800.0, {"birimfiyat": "ÖZEL-82"}),
                ("8.8", "Site dış aydınlatması ve altyapı (External lighting and site infrastructure)", "takım", 1.0, 3_600_000.0, {"birimfiyat": "ÖZEL-83"}),
                ("8.9", "Sığınak kapıları, havalandırması ve donanımı, Sığınak Yönetmeliği (Shelter blast doors, ventilation and equipment)", "takım", 1.0, 3_850_000.0, {"birimfiyat": "ÖZEL-84"}),
            ],
        ),
    ],
    # Turkish price build-up. The Ministry's birim fiyat analyses end with a
    # single "%25 muteahhit kari ve genel giderleri" head that covers overhead,
    # site establishment, general scaffolding, insurance, site management and
    # profit together. It is never split, so it is carried here as one line and
    # categorised as overhead; see project_metadata["markup_note"] for what that
    # costs on the price-analysis sheet. KDV is the general 20 percent rate that
    # applies to construction contracting, taken on the cumulative amount.
    markups=[
        ("Müteahhit kârı ve genel giderler %25 (Contractor profit and overheads, 25 percent)", 25.0, "overhead", "direct_cost"),
        ("KDV %20 (Value added tax at 20 percent)", 20.0, "tax", "cumulative"),
    ],
    total_months=32,
    tender_name="Anahtar teslimi genel yapım işi - Kağıthane karma kullanımlı bina",
    tender_companies=[
        ("Yalınkaya İnşaat Sanayi ve Ticaret A.Ş.", "ihale@yalinkaya.example", 0.97),
        ("Beyçınar Yapı Taahhüt A.Ş.", "teklif@beycinar.example", 1.03),
        ("Deregözü İnşaat Taahhüt Ltd. Şti.", "ihale@deregozu.example", 1.01),
    ],
    tender_packages=[
        (
            "Kazı, iksa ve kaba yapı (Excavation, shoring and structure)",
            "Kazı ve nakliye, fore kazık iksa, jet grout zemin iyileştirmesi, radye temel ve betonarme taşıyıcı sistem.",
            "evaluating",
            [
                ("Yalınkaya İnşaat Sanayi ve Ticaret A.Ş.", "ihale@yalinkaya.example", 0.97),
                ("Beyçınar Yapı Taahhüt A.Ş.", "teklif@beycinar.example", 1.03),
                ("Deregözü İnşaat Taahhüt Ltd. Şti.", "ihale@deregozu.example", 1.01),
            ],
        ),
        (
            "Cephe ve doğrama (Facade and joinery)",
            "Giydirme cephe, kompozit panel kaplama, mantolama, alüminyum doğrama ve cam korkuluk imalatları.",
            "issued",
            [
                ("Sarıçınar Cephe Sistemleri Ltd. Şti.", "teklif@saricinar.example", 0.98),
                ("Akkavak Alüminyum ve Cam A.Ş.", "ihale@akkavak.example", 1.04),
                ("Gökbayır Cephe Uygulama A.Ş.", "teklif@gokbayir.example", 1.02),
            ],
        ),
        (
            "Mekanik ve elektrik tesisat (Mechanical and electrical services)",
            "Sıhhi tesisat, ısıtma, VRF iklimlendirme, yangın söndürme ve algılama, elektrik ve zayıf akım sistemleri.",
            "issued",
            [
                ("Özdemirci Tesisat Taahhüt A.Ş.", "ihale@ozdemirci.example", 0.99),
                ("Karaçalı Elektromekanik Ltd. Şti.", "teklif@karacali.example", 1.05),
                ("Turnalı Mekanik Tesisat A.Ş.", "ihale@turnali.example", 1.02),
            ],
        ),
        (
            "İnce yapı ve mimari uygulama (Finishes and architectural fit-out)",
            "Sıva, boya, şap, seramik, doğal taş, asma tavan, kapı ve mutfak imalatları ile çevre düzenlemesi.",
            "draft",
            [
                ("Mavigöl Yapı Uygulama Ltd. Şti.", "teklif@mavigol.example", 0.98),
                ("Erdemli İç Yapı ve Dekorasyon A.Ş.", "ihale@erdemliicyapi.example", 1.03),
                ("Çamlıbel Mimari Uygulama A.Ş.", "teklif@camlibel.example", 1.01),
            ],
        ),
    ],
    schedule_activities=[
        ("Ruhsat, şantiye kurulumu ve hafriyat izinleri (Permits, site set-up and spoil consents)", "2026-03-02", "2026-04-30"),
        ("Fore kazık iksa ve ankraj imalatı (Bored-pile shoring and anchors)", "2026-04-01", "2026-07-15"),
        ("Kazı ve nakliye (Bulk excavation and haulage)", "2026-05-01", "2026-09-15"),
        ("Jet grout zemin iyileştirmesi (Jet-grout ground improvement)", "2026-08-01", "2026-10-15"),
        ("Radye temel ve bodrum betonarmesi (Raft and basement structure)", "2026-09-15", "2027-01-31"),
        ("Temel ve bodrum su yalıtımı (Raft and basement tanking)", "2026-11-01", "2027-02-28"),
        ("Üst yapı betonarme imalatı (Superstructure concrete frame)", "2027-01-15", "2027-12-31"),
        ("Dolgu duvar ve bölme imalatı (Infill masonry and partitions)", "2027-05-01", "2028-03-31"),
        ("Cephe ve doğrama uygulaması (Facade and joinery)", "2027-09-01", "2028-06-30"),
        ("Çatı yalıtım ve örtü işleri (Roof insulation and covering)", "2028-01-15", "2028-04-30"),
        ("Mekanik tesisat kaba imalatı (Mechanical first fix)", "2027-07-01", "2028-05-31"),
        ("Elektrik ve zayıf akım kaba imalatı (Electrical and ELV first fix)", "2027-08-01", "2028-06-30"),
        ("Asansör montajı ve devreye alma (Lift installation and commissioning)", "2028-01-02", "2028-07-31"),
        ("İnce yapı ve kaplama işleri (Finishes and coverings)", "2028-02-01", "2028-09-30"),
        ("Otopark ve çevre düzenlemesi (Car park fit-out and external works)", "2028-05-01", "2028-09-30"),
        ("Test, devreye alma ve yapı denetim kabulü (Testing, commissioning and inspection sign-off)", "2028-07-01", "2028-10-31"),
    ],
    project_metadata={
        "address": "Merkez Mahallesi, Cendere Caddesi No: 42, 34406 Kağıthane / İstanbul, Türkiye",
        "client": "Kağıthane Vadi Gayrimenkul Geliştirme A.Ş.",
        "architect": "Üçgen Avlu Mimarlık ve Tasarım Ofisi",
        "structural_engineer": "Sarnıç Yapı Mühendislik (deprem hesabı / seismic design)",
        "quantity_surveyor": "Ölçüt Metraj ve Keşif Danışmanlığı",
        "building_inspection": "4708 sayılı Yapı Denetimi Hakkında Kanun kapsamında yetkili yapı denetim kuruluşu",
        "gfa_m2": 34000,
        "site_area_m2": 4800,
        "storeys": "2 bodrum + zemin + 15 normal kat (2 basements, ground and 15 upper floors)",
        "building_height_m": 52.3,
        "flats": 120,
        "office_area_m2": 6000,
        "retail_area_m2": 3000,
        "parking_spaces": 240,
        "structure_system": (
            "Süneklik düzeyi yüksek betonarme perde ve çerçevelerden oluşan karma sistem, "
            "jet grout ile iyileştirilmiş zemin üzerinde radye temel. TBDY 2018 Tablo 4.1'e göre "
            "R = 7, D = 2.5, I = 1.00. High-ductility RC shear wall plus frame dual system on a "
            "raft over jet-grouted ground."
        ),
        "seismic_design": (
            "TBDY 2018 (Türkiye Bina Deprem Yönetmeliği, yürürlük 01.01.2019; DBYBHY 2007 yerine). "
            "Deprem yer hareketi AFAD Türkiye Deprem Tehlike Haritası'ndan saha koordinatına göre "
            "alınır; eski beş deprem bölgesi sınıflandırması kaldırılmıştır. Bu proje için kabuller: "
            "yerel zemin sınıfı ZD (Kağıthane alüvyonu), Deprem Tasarım Sınıfı DTS = 1, Bina Kullanım "
            "Sınıfı BKS = 3, Bina Önem Katsayısı I = 1.00, Bina Yükseklik Sınıfı BYS = 3 (yapı "
            "yüksekliği 52,30 m). Seismic actions come from the AFAD hazard map at the site "
            "coordinates, not from a zone number; the values above are design assumptions to be "
            "confirmed by the ground investigation."
        ),
        "seismic_scope_note": (
            "Deprem tasarımı bu keşifte yalnızca bir not değildir. C35/45 perde ve kolon betonu, "
            "yüksek donatı oranı ve sarılma bölgesi etriyeleri (poz 2.4, 2.7), perde düşey "
            "donatısında mekanik ekleme manşonu ve filiz ekimi (poz 2.11, 2.12), deprem derzi "
            "(poz 2.10), dolgu duvar bağlantı elemanları (poz 3.3), asma tavan sismik askıları "
            "(poz 5.8) ve mekanik tesisat sismik destekleri (poz 6.11) TBDY 2018 gereklerinden "
            "doğar. TBDY 2018 Bölüm 6, yapısal olmayan elemanların bağlantılarını da kapsar, "
            "bu yüzden maliyet mimari ve tesisat bölümlerine de yayılır."
        ),
        "construction_standards": [
            "TBDY 2018 Türkiye Bina Deprem Yönetmeliği",
            "TS 500 Betonarme Yapıların Tasarım ve Yapım Kuralları",
            "TS 498 Yapı Elemanlarının Boyutlandırılmasında Alınacak Yüklerin Hesap Değerleri",
            "TS EN 206 / TS 13515 Beton - Özellik, performans, imalat ve uygunluk",
            "TS 708 Beton Çeliği - Donatı çeliği (B420C)",
            "TS 825 Binalarda Isı Yalıtım Kuralları",
            "Binaların Yangından Korunması Hakkında Yönetmelik (BYKHY)",
            "Binalarda Enerji Performansı Yönetmeliği (BEP)",
            "Planlı Alanlar İmar Yönetmeliği; Otopark Yönetmeliği; Sığınak Yönetmeliği",
        ],
        "estimating_method": (
            "Metraj ve birim fiyat. Yaklaşık maliyet, Yapım İşleri İhaleleri Uygulama Yönetmeliği "
            "esaslarına göre, Çevre, Şehircilik ve İklim Değişikliği Bakanlığı birim fiyat ve "
            "rayiçleri ile piyasa fiyat araştırması birlikte kullanılarak düzenlenir."
        ),
        "regulator": (
            "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı (birim fiyat ve yönetmelikler); yapı "
            "ruhsatı Kağıthane Belediyesi, İstanbul Büyükşehir Belediyesi görüşü ile; yapım süresince "
            "4708 sayılı Kanun kapsamında yapı denetim kuruluşu denetimi ve yapı kullanma izin belgesi."
        ),
        "markup_note": (
            "Bu keşifteki birim fiyatlar müteahhit kârı ve genel giderler hariçtir, bu nedenle %25 "
            "ayrı bir satır olarak eklenmiştir. Bakanlığın yayımladığı birim fiyatlar ise bu %25'i "
            "zaten içerir; yayımlanmış poz fiyatı kullanılıyorsa satır ikinci kez eklenmemelidir. "
            "The published Ministry unit prices already contain the 25 percent head, so an estimate "
            "built from them must not carry the markup line as well. The head is a single item in "
            "Turkish practice and is not split into overhead and profit, so the per-position price "
            "analysis attributes all of it to overhead and draws no profit line at all."
        ),
        "tax_note": (
            "İnşaat taahhüt işlerinde genel KDV oranı %20'dir (10.07.2023'ten itibaren). Konut "
            "teslimleri ve bazı sosyal konut taahhüt işleri için indirimli oranlar bulunur, bu "
            "yüzden her projenin kendi vergi durumu ayrıca belirlenmelidir. Construction "
            "contracting carries the general 20 percent VAT rate; reduced rates exist for certain "
            "dwelling deliveries and social-housing contracts and must be checked per project."
        ),
        "fire_safety_note": (
            "Yapı yüksekliği 52,30 m olduğundan bina, Binaların Yangından Korunması Hakkında "
            "Yönetmelik anlamında yüksek binadır (yapı yüksekliği 30,50 m üzeri); yağmurlama "
            "sistemi, kaçış merdiveni basınçlandırması, yangın asansörü ve duman tahliyesi bu "
            "nedenle zorunludur. Üç ayrı yükseklik eşiği karıştırılmamalıdır: yangın yönetmeliğinin "
            "30,50 m sınırı, TBDY 2018'in Bina Yükseklik Sınıfı ölçeği ve İstanbul'da yüksek yapı "
            "kabul edilen imar eşiği farklı yönetmeliklerden gelir ve aynı sayı değildir."
        ),
        "price_level_note": (
            "Fiyat seviyesi İstanbul 2026-Q1'dir ve belge üzerinde bir kez belirtilir. Türkiye'de "
            "enflasyon nedeniyle tarihi ve endeksi verilmeyen bir TL toplamı hiçbir şeyle "
            "karşılaştırılamaz. Gerçek bir sözleşmede Yapım İşleri Fiyat Farkı Esasları uyarınca "
            "TÜİK Yurt İçi Üretici Fiyat Endeksi üzerinden fiyat farkı hesaplanır; endeks serisi ve "
            "a, b katsayıları bu şablonda modellenmemiştir."
        ),
        "contract": "Anahtar teslimi götürü bedel yapım sözleşmesi (lump-sum turnkey construction contract)",
        "headline_cost_try": (
            "İmalat bedeli yaklaşık 1,28 milyar TL; kâr ve genel giderler dahil yaklaşık 1,60 milyar TL; "
            "KDV dahil yaklaşık 1,91 milyar TL (approx. TRY 1.91 billion including VAT)"
        ),
    },
    budget_boq_name="Kontrol Bütçesi - Bakanlık birim fiyatları 2026 (Control Budget)",
    planned_budget=1_600_000_000.0,
    actual_spend_ratio=0.32,
    spi_override=0.97,
    cpi_override=1.03,
)
