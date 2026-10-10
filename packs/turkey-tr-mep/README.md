# Turkey MEP Contractor Pack

For a mechanical, electrical and plumbing contractor working in Türkiye. One
pack to install: it carries the whole Türkiye country configuration and opens
every user on a short menu built around what an installer does.

## Why this is one pack and not two

An installation runs one pack at a time. A country pack and an industry pack
cannot be installed side by side, so this pack has to bring the country with
it. It does not copy the country pack. Its manifest is built from the
`turkey-tr` manifest when it is loaded and replaces only its own fields, so a
correction to the Türkiye configuration reaches this pack without an edit
here.

`turkey-tr` therefore has to be present, and the pack is not listed without
it. In OpenConstructionERP itself both ship together: the wheel, the Docker
image and the desktop build carry the two directories side by side, and this
pack reads its neighbour. Installed from its own distribution, the country
pack is a declared dependency.

Inherited from `turkey-tr`, unchanged: the Turkish interface, the lira, the
`turkey` estimating method, the `birimfiyat` rule set and classification, the
national cost base, the demo project, the public holidays and the market
metadata. Read that pack's README for what each one means; the review status
stated there applies here too.

The five reference documents of the country pack are not repeated here. They
are files of `turkey-tr`, they are found from that pack whichever of the two
is active, and this pack names none of its own.

## What this pack adds

**A starting menu.** The pack names the company profile "MEP / Building
Services Contractor". A user who has not chosen a profile opens on that
profile's workspace: the installer's screens in eight groups, in the order
the work runs.

| Group | Screens |
|---|---|
| Site records | Daily diary, correspondence, RFIs, meetings, schedule, labour timesheets, contacts |
| Engineering and approvals | Submittals, transmittals, drawing sheets, documents |
| Procurement and logistics | Purchase orders, requests for quotation, site deliveries |
| Commercial | Contracts, subcontractors, progress, progress claims (hakediş), variations, invoices, payments, tax rates |
| Cost and estimating | Bill of quantities, quantity takeoff |
| Quality, testing and commissioning | Inspection requests and material records, NCRs, punch list, commissioning |
| Health and safety | Safety, permits and toolbox talks |
| Handover | Closeout, warranties and defects liability |

Every other screen is one click away under "More modules", which is closed
until the user opens it. Nothing is written to anybody's account: a user who
has chosen a profile keeps it, and anyone can pick another on Modules >
Company Profiles. The person who keeps the site registers can pick the job
profile "Site Records / Document Control" there, a short list of the diary,
correspondence, RFIs, submittals, variations, documents and contacts.

The workspace also keeps out from under "More modules" the screens for
another trade, for the client's or designer's side, for a developer who sells
units and for a public authority. They are not disabled. Search, a link and
Advanced mode still open them.

**A module set.** The modules the menu opens are switched on when the pack is
applied, in case an admin had switched one off. Twenty-four modules an
installer has no use for can be switched off, and only when the admin applying
the pack confirms it:

- estimating for other trades and for the client's side: formwork, rebar
  schedules, the elemental cost plan, temporary works;
- public grants, the statutory regimes of other countries (certified payroll,
  the payment clock), embodied carbon, the sales-side value rollup, marketing
  leads;
- a developer tool, the architecture map;
- the thirteen regional data packs of other markets. None of them serves
  Türkiye, Hungary or Spain.

## What switching a module off does and does not do

It removes the module's API for every user of the installation, and the
module's menu row with it. It is not a per-user setting and it is not how the
menu gets short: the short menu comes from the company profile. An admin
switches a module back on under Modules > System Modules, and un-applying the
pack restores what it switched off.

The setup wizard's one-click install does not switch anything off. It says so
before the install and again on its last step, with the number of modules
left on and a link to this pack on the Modules page. To switch them off, open
the pack there and tick the box in its setup dialog.

Some further modules are of no use to an installer and stay on, because they
are core modules that cannot be switched off, or because a module that stays
on depends on them. The profile keeps their rows out of the menu instead.

## What the platform provides for a Turkish contractor

These are features of OpenConstructionERP, not of this pack. They are there
with or without it, and the pack's menu is where an installer finds them.

- The site registers (RFIs, submittals, correspondence, change orders,
  transmittals, variations, claims evidence) and the daily diary export as a
  PDF or a workbook in Turkish or English.
- The hakediş progress payment certificate is computed for unit price and
  lump sum contracts and printed in Turkish, English or both; a line whose
  input is missing is printed as held and marks the document a draft.
- Withheld VAT (KDV tevkifatı), income tax withholding (stopaj) and stamp duty
  (damga vergisi) are computed from dated rate tables, shown with their basis,
  rate and legal reference, and applied to a document only when a person
  confirms them.
- A UBL-TR e-Fatura file is written unsigned, with a validation report, for a
  licensed integrator to sign and submit. Acceptance by an integrator has not
  been confirmed.

Not built: signing or submitting the e-Fatura, and any connection to an
integrator or to the revenue administration.

## Projects in other countries

The pack is for Türkiye. A project in Türkiye created while it is active
inherits the `turkey` estimating method and the `birimfiyat` rule set. A
project created for another country takes the rule sets and method of that
country's own pack when one ships (Hungary and Spain both have one) and the
neutral defaults when none does. A project is read as being in another
country from its country, its region or an address that names one; a project
that names none is taken to be in Türkiye.

## The demo project

`mixed-use-istanbul`, inherited from the country pack. It is a whole-building
estimate from a main contractor's side, not an MEP subcontract. There is no
MEP subcontract demo yet.

Every way of installing the pack seeds that one project, the same one the
country pack seeds.

## Review status

Nothing statutory in this pack is its own: the numbering, the units, the
rates and the tax tables are the country pack's and the platform's. They are
drawn from the published legislation and are pending review by a Turkish
quantity surveyor and a Turkish accountant. Do not rely on them for a tender
or a tax filing before that review. Nothing here is legal or tax advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules, Packs
tab: find "Turkey MEP Contractor Pack", then Activate pack. The first-run
wizard also lists it, marked as a specialised variant, next to the Turkey
Construction Pack it is built on.

To run a workspace that boots straight into it:

```bash
OE_PACK=turkey-tr-mep openconstructionerp serve
```

## License

AGPL-3.0-or-later, the same licence as OpenConstructionERP. No part of this
pack is reserved under a partnership agreement.

Contact: info@datadrivenconstruction.io
