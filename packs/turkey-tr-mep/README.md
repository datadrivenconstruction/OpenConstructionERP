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
here. `turkey-tr` therefore has to be present: it is a dependency of this
pack's distribution, and in a source checkout it is the directory next to this
one.

Inherited from `turkey-tr`, unchanged: the Turkish interface, the lira, the
`turkey` estimating method, the `birimfiyat` rule set and classification, the
five reference documents, the national cost base, the demo project, the public
holidays and the market metadata. Read that pack's README for what each one
means; the review status stated there applies here too.

## What this pack adds

**A starting menu.** The pack names the company profile "MEP / Building
Services Contractor". A user who has not chosen a profile opens on that
profile's workspace: 35 rows, 32 of them in eight groups, in the order the
work runs.

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
profile "Site Records / Document Control" there, which is ten rows: the
dashboard, inbox and projects, then the diary, correspondence, RFIs,
submittals, variations (with extension of time claims on a tab), documents and
contacts.

The workspace also keeps 27 screens out from under "More modules": the ones
for another trade, for the client's or designer's side, for a developer who
sells units and for a public authority. They are not disabled. Search, a link
and Advanced mode still open them.

**A module set.** Twenty modules the menu opens are switched on when the pack
is applied, in case an admin had switched one off. Twenty-four modules an
installer has no use for are switched off, and only when the admin applying
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
menu gets short: the twenty-four modules own nine menu rows between them. The
short menu comes from the company profile. An admin switches a module back on
under Modules > System Modules, and un-applying the pack restores what it
switched off.

The setup wizard's one-click install does not confirm the disables, so there
the list is reported as skipped. To switch the modules off, apply the pack
from the Modules page and tick the box.

Seventeen more modules are of no use to an installer and stay on, because
they are core modules that cannot be switched off, and property development
stays on because the map module depends on it. The profile keeps their rows
out of the menu instead.

## Projects in other countries

The pack is for Türkiye. A project created while it is active inherits the
`turkey` estimating method and the `birimfiyat` rule set whatever country the
project names, and takes Türkiye as its country when the form does not supply
a country code. A contractor who also works abroad should set the country and
the classification standard when creating such a project and switch its
estimating method in the project settings.

## The demo project

`mixed-use-istanbul`, inherited from the country pack. It is a whole-building
estimate from a main contractor's side, not an MEP subcontract. There is no
MEP subcontract demo yet.

## License

AGPL-3.0-or-later, the same licence as OpenConstructionERP. No part of this
pack is reserved under a partnership agreement.

Contact: info@datadrivenconstruction.io
