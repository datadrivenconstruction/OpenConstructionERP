# 04 — 50 User Scenarios (SME, first-time users)

> 50 realistic workflows designed **before** exploring the app. Each scenario states:
> - **Persona** — who is doing it
> - **Input** — what they have / what they bring
> - **Goal** — what they want to accomplish
> - **Expected exit knowledge** — what they should know after completing it
> - **Minimum path** — the clicks a novice would naturally try
>
> Phase 2 (`05-scenarios-run.md`) records actual execution against the live VPS
> and grades logic, quality, UX.

---

## A. Onboarding & Setup (1–5)

### #1 — First login, new company, Deutsch
- **Persona:** Handwerker (Max, 52, computer-moderate)
- **Input:** new account credentials, knows company is "Muster GmbH"
- **Goal:** land on an empty-but-usable dashboard
- **Exit knowledge:** where the sidebar is, what a "Schrank" is, where to upload a document
- **Path:** login → wizard step 1 (Deutsch) → wizard step 2 (Handwerk) → wizard step 3 (Fertig) → dashboard

### #2 — Pick English language at first login
- **Persona:** Thomas, German-born but prefers English UI
- **Input:** same
- **Goal:** app switches to English
- **Exit knowledge:** language persists between reloads
- **Path:** login → wizard → click English → Get started → dashboard should be English

### #3 — Skip onboarding ("Überspringen")
- **Persona:** impatient user who already knows apps
- **Goal:** dashboard immediately
- **Exit knowledge:** skip works; "Einstellungen → Branche" exists to change later
- **Path:** login → wizard → Überspringen → dashboard

### #4 — Invite a colleague
- **Persona:** admin Max, wants to add bookkeeper Maria
- **Input:** Maria's email
- **Goal:** invite sent, Maria's slot visible in Admin → Benutzer
- **Exit knowledge:** Maria receives email (logged in dev), can set password
- **Path:** Admin → Benutzer → Einladen → form → submit → see pending invitation

### #5 — Change my password
- **Persona:** any user after an org-mandated rotation
- **Input:** current + new password
- **Goal:** password changed, next login uses new
- **Path:** Avatar → Einstellungen → Profil → "Passwort ändern" → form → Speichern

---

## B. Documents (6–10)

### #6 — Upload an invoice PDF
- **Persona:** Sachbearbeiter (Maria)
- **Input:** a real PDF in Downloads folder
- **Goal:** PDF archived in the correct Schrank with auto-classification
- **Exit knowledge:** OCR runs, document type detected, it appears in list
- **Path:** Dokumente → Hochladen → pick file → auto-classify → see in list

### #7 — Upload multiple files at once
- **Persona:** same
- **Input:** 5 PDFs
- **Goal:** all 5 archived
- **Path:** Dokumente → Hochladen → drop all → see 5 rows

### #8 — Find all "Rechnungen" from 2026
- **Persona:** Bookkeeper before a tax filing
- **Input:** knows she wants invoices only, year 2026
- **Goal:** filtered list
- **Path:** Dokumente → Filtern → Typ=Rechnung + Jahr=2026 → results

### #9 — Archive a draft document (GoBD-sign it)
- **Persona:** compliance-aware user
- **Goal:** document becomes WORM (cannot modify)
- **Exit knowledge:** after archive, edit/delete are disabled; a hash is stored
- **Path:** pick document → Detail → Archivieren → confirm

### #10 — Use Spotlight search (Cmd+K)
- **Persona:** power user
- **Input:** knows invoice number "RE-2026-0001"
- **Goal:** jump to that invoice in 2 seconds
- **Path:** Cmd+K → type "RE-2026-0001" → Enter → lands on invoice detail

---

## C. Cabinets (11–13)

### #11 — Create a new Schrank "Verträge"
- **Persona:** admin
- **Goal:** empty cabinet "Verträge" visible in sidebar + list
- **Path:** Schränke → Neu → name="Verträge" → Speichern

### #12 — Add a required field "Vertragspartner" to a Schrank
- **Persona:** admin wants to enforce metadata
- **Goal:** cabinet has "Vertragspartner" as required when uploading
- **Path:** Schränke → Verträge → Felder → +Feld → name, type=text, required

### #13 — Move a document between Schränke
- **Persona:** Maria filed a doc wrong
- **Goal:** doc now lives in the right cabinet
- **Path:** open doc → Verschieben → pick cabinet → Speichern

---

## D. Invoicing (14–19)

### #14 — Create a draft invoice for an existing customer
- **Persona:** Max invoicing a regular
- **Input:** customer "Audit Kunde GmbH" exists
- **Goal:** RE-2026-0NNN draft saved with 1 line item
- **Path:** Rechnungen → + Neu → pick customer → add line → Speichern

### #15 — Send the invoice by email
- **Persona:** same
- **Input:** customer has email
- **Goal:** status flips to "Gesendet", email logged
- **Path:** invoice detail → Senden → confirm → status update

### #16 — Mark invoice as paid
- **Persona:** after bank reconcile
- **Goal:** status "Bezahlt" + Zahldatum
- **Path:** invoice → "Als bezahlt markieren" → date → Speichern

### #17 — Send 1st Mahnung for overdue invoice
- **Persona:** Max watches the overdue tab
- **Goal:** mahnstufe=1, reminder letter generated
- **Path:** Mahnwesen → overdue list → select → Mahnung 1 → Senden

### #18 — Generate a recurring invoice template (monthly rent)
- **Persona:** landlord-style user
- **Input:** Subscription customer
- **Goal:** template runs automatically each month
- **Path:** Rechnungen → Serienrechnungen → Neu → setup monthly → save

### #19 — Export XRechnung ZIP for an invoice
- **Persona:** public-sector customer requires XRechnung
- **Goal:** ZIP download with UBL 2.1 XML + PDF/A
- **Path:** invoice → Exportieren → XRechnung → file downloaded

---

## E. Accounting (20–23)

### #20 — Generate EÜR for 2026
- **Persona:** Kleinunternehmer doing yearly tax
- **Goal:** EÜR overview with Einnahmen - Ausgaben = Gewinn
- **Path:** Buchhaltung → EÜR → 2026 → view total

### #21 — Export DATEV for March 2026
- **Persona:** sending to Steuerberater
- **Goal:** DATEV CSV downloaded
- **Path:** Buchhaltung → DATEV-Export → period → Export

### #22 — View UStVA for Q1 2026
- **Goal:** USt-Vorauszahlung amount visible
- **Path:** Buchhaltung → UStVA → Q1 2026

### #23 — Assign a document to a Konto (Kontierung)
- **Persona:** Maria
- **Input:** unassigned invoice
- **Goal:** SKR04 account assigned + accounting entry created
- **Path:** Dokumente → invoice → Kontierung → pick account → speichern

---

## F. Banking (24–26)

### #24 — Connect a bank via FinTS
- **Persona:** Max with Commerzbank account
- **Input:** FinTS credentials
- **Goal:** account listed with balance
- **Path:** Banking → Bank verbinden → choose bank → credentials → sync

### #25 — Import MT940 manually
- **Persona:** same but offline
- **Input:** .sta or .mt940 file
- **Goal:** transactions ingested
- **Path:** Banking → Importieren → upload → see list

### #26 — Reconcile a transaction with an invoice
- **Persona:** Maria matching
- **Goal:** invoice status = Bezahlt automatically
- **Path:** Banking → Abgleich → pick txn → pick invoice → bestätigen

---

## G. Contacts / CRM (27–30)

### #27 — Add a new customer manually
- **Persona:** after a phone call
- **Input:** name, email, phone, address
- **Goal:** customer saved + visible in list
- **Path:** Kontakte → Neu → fill → Speichern

### #28 — Scan a business card
- **Persona:** after a fair
- **Input:** photo/scan of card
- **Goal:** contact extracted via OCR + reviewable
- **Path:** Kontakte → Visitenkarte scannen → upload → confirm extraction

### #29 — Import contacts from CSV
- **Persona:** switching from Excel
- **Input:** CSV with standard columns
- **Goal:** N contacts imported, duplicates flagged
- **Path:** Kontakte → Importieren → upload CSV → map → confirm

### #30 — Log a call / communication
- **Persona:** after talking to customer
- **Goal:** timeline entry appears in contact detail
- **Path:** Contact detail → Kommunikation → +Neu → type=phone → save

---

## H. Contracts (31–33)

### #31 — Add a new Wartungsvertrag (service contract)
- **Persona:** Max recurring maintenance
- **Input:** partner, start-date, value
- **Goal:** contract status="aktiv", termination deadline computed
- **Path:** Verträge → Neu → form → Speichern

### #32 — Get alerted about expiring contracts
- **Persona:** admin
- **Goal:** see "Läuft bald aus" list in dashboard
- **Path:** Dashboard → expiring widget OR Verträge → "Läuft bald aus" tab

### #33 — Terminate a contract before notice deadline
- **Persona:** escaping a bad vendor
- **Goal:** status=gekündigt, date stored
- **Path:** contract detail → Kündigen → confirm reason → save

---

## I. Projects & Construction (34–36)

### #34 — Start a project "Badsanierung Müller"
- **Persona:** Handwerker
- **Input:** client contact, budget hours, hourly rate
- **Goal:** project created, visible in Projekte
- **Path:** Projekte → +Neu → name + client + hours + rate → save

### #35 — Add a daily Bautagebuch entry
- **Persona:** site foreman
- **Input:** date, weather, workers, activity
- **Goal:** diary entry, counted in project
- **Path:** Bautagebuch → +Eintrag → fill → save

### #36 — Take an Aufmaß measurement (area)
- **Persona:** site measurer
- **Input:** room dimensions
- **Goal:** area calculated automatically, added to project
- **Path:** Aufmaß → +Neu → add measurement → see auto-sum

---

## J. Tasks & Workflows (37–40)

### #37 — Create a simple task "Rechnung prüfen"
- **Goal:** task in "Offen" queue, assignable
- **Path:** Tasks → + Neu → name + due → save

### #38 — Assign task to Maria
- **Goal:** Maria sees it in her inbox
- **Path:** task detail → Zuweisen → Maria → save

### #39 — Complete the task
- **Goal:** status=erledigt, time tracked
- **Path:** task → "Abschließen" → save

### #40 — Create a 3-step approval workflow for invoices
- **Persona:** admin
- **Goal:** workflow ready to trigger on new invoice
- **Path:** Workflows → +Neu → designer → 3 nodes → Speichern → aktivieren

---

## K. Time & HR (41–43)

### #41 — Log 8 hours on project X
- **Persona:** Maria
- **Goal:** entry saved, project total updates
- **Path:** Zeiterfassung → +Neu → project+hours → save

### #42 — Request 3 days vacation
- **Persona:** employee
- **Goal:** request in pending queue
- **Path:** Urlaub → +Antrag → dates → save

### #43 — Approve a vacation request
- **Persona:** Manager Thomas
- **Goal:** request status=approved
- **Path:** Urlaub → pending → approve

---

## L. Compliance / GoBD (44–46)

### #44 — Verify audit chain integrity
- **Persona:** before an audit visit
- **Goal:** "Kette verifiziert — OK" banner
- **Path:** Compliance → Kette verifizieren → wait → success

### #45 — Export GDPdU ZIP
- **Persona:** tax auditor requests data
- **Goal:** ZIP with documents + index.xml downloaded
- **Path:** Compliance → GDPdU-Export → period → Exportieren

### #46 — View Aufbewahrungsfristen monitor
- **Persona:** before housekeeping
- **Goal:** list of documents past retention
- **Path:** Compliance → Aufbewahrungsfristen

---

## M. Search / AI (47–48)

### #47 — Ask AI Copilot "Wie hoch waren die Rechnungen im März?"
- **Goal:** Copilot returns a summed figure with source citation
- **Path:** Copilot → prompt → see answer

### #48 — Semantic search "Stromrechnung"
- **Goal:** find all electricity-related invoices even if "Strom" isn't in title
- **Path:** Suche → query → results ranked

---

## N. Cross-cutting (49–50)

### #49 — Switch to dark mode
- **Persona:** evening user
- **Goal:** app theme flips, choice persists
- **Path:** Einstellungen → Erscheinungsbild → Dunkel → reload

### #50 — Log out
- **Goal:** redirected to login, tokens cleared
- **Path:** Avatar → Abmelden → login page
