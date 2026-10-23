# Pakistan Construction Pack

Country pack for contractors in Pakistan, private and public. It carries no code of its own: it composes
neutral platform modules and data rows.

- Bill: sales tax carried as a line of its own (rule set `pakistan`, markup template PK). Federal GST on goods is 18 percent; construction services are taxed by the province (tax table rows `PRA_ST` Punjab, `SRB_ST` Sindh, `KPRA_ST` Khyber Pakhtunkhwa).
- Withholding: income tax under section 153(1)(c) of the Income Tax Ordinance as four selectable payee classes (company or other, on or off the Active Taxpayer List), payment taxes table `data_pk`.
- Payment: interim payment certificate, 10 percent retention up to 5 percent of the Contract Price, 28 days to pay (contract defaults row PK, payment clock `pk_pec_sbd_clause_60`).
- Public works: defaults of the PEC Standard Bidding Documents for Works (mobilization advance up to 15 percent, performance security 10 percent, delay damages cap 10 percent) and the Clause 70 price adjustment `pk_pec_sbd_clause_70`. All flagged for expert review, shown and never enforced. No index values are shipped.
- Units: `sft`, `cft`, `rft` and "running ft" are aliases of ft2, ft3 and ft. `marla` and `kanal` are units of their own with no fixed m2 factor, because a marla is 272.25 sq ft in the federal survey and 225 sq ft in Punjab revenue practice. The user converts with the factor the site uses.
- Calendar: Monday to Friday working week, national holidays, Eid and Ashura spans with the moon-sighting observances of 2025 recorded.
- Classification: neutral (MasterFormat). The provincial schedules are not tied to a published classification the platform can compose.
- Demo projects: RCC Basic Health Unit in Punjab (`bhu-punjab`, sales tax of Punjab) and a government primary school in Karachi (`school-karachi`, sales tax of Sindh).

## Sources and status

Every figure is flagged `unconfirmed` or provisional and needs review by a Pakistani quantity surveyor and tax adviser before it is relied on for a tender or a tax filing.

- Income tax rates: Federal Board of Revenue withholding rate card updated up to 30 June 2026.
- Contract defaults, public works figures, price adjustment: Standard Bidding Documents for Procurement of Works (large contracts, 2015), harmonized with the Pakistan Engineering Council.
- Provisional: the provincial rates for Punjab (16 percent), Sindh and Khyber Pakhtunkhwa (15 percent) and the reduced government works rates (Punjab 5, Sindh 5) come from secondary sources. The Khyber Pakhtunkhwa government works rate (4 percent) was read on the authority's own notification. Balochistan is not shipped.
- Holidays: Cabinet Division yearly circular and the 2025 Eid press releases. Islamic dates follow the Umm al-Qura calendar, which can differ from the Pakistani moon sighting by one to two days.

## Not shipped

- Rates. The provincial Market Rate Systems and Composite Schedules of Rates (Punjab, Sindh, Khyber Pakhtunkhwa and Balochistan) exist and are published by the provincial works departments. Loading them is a later, separate step; no rate is in this pack.
- Sales tax withheld by the paying body, income tax on services under section 153(1)(b), minimum tax, exemption certificates, stamp duty.
- Pakistani electronic invoice profile of the Federal Board of Revenue.

---

# Baupaket Pakistan

Laenderpaket fuer Bauunternehmen in Pakistan: Umsatzsteuer als eigene Zeile (bundesweite GST 18 Prozent auf Waren, Dienstleistungssteuer der Provinz auf Bauleistungen), einbehaltene Einkommensteuer nach Abschnitt 153(1)(c) in vier Zahlerklassen, Zwischenzahlungszertifikate mit 10 Prozent Einbehalt und 28 Tagen Zahlungsfrist, Standardwerte der PEC-Ausschreibungsunterlagen und Klausel 70 zur Preisanpassung, Marla und Kanal als Einheiten, Feiertage, Pakistanische Rupie, Demoprojekt Basisgesundheitsstation in Punjab. Alle Werte sind unbestaetigt, bis ein pakistanischer Fachmann sie geprueft hat. Preislisten (Market Rate Systems, Composite Schedules of Rates der Provinzen) sind nicht enthalten und folgen in einem spaeteren Schritt.

---

# Пакет для Пакистана

Страновой пакет для подрядчиков в Пакистане: налог с продаж отдельной строкой (федеральный GST 18 процентов на товары, провинциальный налог на услуги для строительных работ), удерживаемый подоходный налог по разделу 153(1)(c) в четырёх классах получателя, промежуточные платёжные сертификаты с удержанием 10 процентов и сроком оплаты 28 дней, типовые значения тендерной документации PEC и пункт 70 об индексации цен, марла и канал как единицы, праздничные дни, пакистанская рупия, демо-проект: базовая медицинская амбулатория в Пенджабе. Все значения не подтверждены до проверки пакистанским специалистом. Расценки (провинциальные Market Rate Systems и Composite Schedules of Rates) не включены и будут отдельным шагом.
