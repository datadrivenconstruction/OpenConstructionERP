# OpenConstructionERP documentation

OpenConstructionERP is an open, self-hosted platform for construction estimating and project delivery. It covers the whole job in one place: build a bill of quantities, take off quantities from drawings and models, price the work against national cost bases, turn a BIM model into cost and carbon, run a tender, plan and control the programme, and capture what happens on site. It is modular, so you enable only the parts you need, and more than 160 modules ship in the box.

This page is the map for the written documentation. Pick the path that matches why you are here, or scroll the sections below.

## Choose your path

Three ways in, depending on why you are here.

- New to the platform. Read the short overview at the foot of this page to see what the platform does and how the pieces connect. Then install it, the desktop app is the quickest start, or run `pip install openconstructionerp`, and sign in with the demo account to open a sample project.
- Here to use it. Go to the [User guide](./user-guide/README.md). It walks the main workflows end to end, one short page each, in the order most teams meet them: from a drawing to a priced, validated estimate, then on to tender, programme and site.
- Here to build on it. Go to the [Platform and builder guide](./platform/README.md). It explains the module system and how to ship your own module without editing the core.

## User guide

The main workflows, one short page each. Full index: [User guide](./user-guide/README.md). Each page explains what a feature is for, when to reach for it, the steps to use it, and how it connects to the rest of the platform.

Measure and estimate:

- [Quantity takeoff from drawings and models](./user-guide/quantity-takeoff.md) - measure from PDFs, DWGs and BIM models and push the numbers into the BOQ.
- [Estimating and the bill of quantities](./user-guide/estimating-and-boq.md) - build a priced BOQ, from a rough order of magnitude to a full tender submission.
- [BIM to cost and carbon (5D and 6D)](./user-guide/bim-to-cost-and-carbon.md) - convert a model to structured quantities, price it over time, and account for its carbon.
- [Design options comparison](./user-guide/design-options.md) - upload competing design variants and weigh them on priced BOQ and cost per option.

Price, check, deliver:

- [World cost bases and multi-base comparison](./user-guide/world-cost-bases.md) - national cost databases, currency-aware pricing, and price spread across regions.
- [The validation pipeline](./user-guide/validation.md) - the traffic-light checks that keep an estimate clean and compliant.
- [Tendering and bid comparison](./user-guide/tendering-and-bids.md) - package the work, invite subcontractors, and compare bids side by side.
- [Planning and cost control](./user-guide/planning-and-cost-control.md) - 4D schedule, 5D cost model, earned value, forecasts and cash flow.
- [Field and site operations](./user-guide/field-and-site.md) - daily diary, inspections, safety, logistics and the record that holds up later.

## Cost data

- [World cost bases and multi-base comparison](./user-guide/world-cost-bases.md) - what the national cost databases are and how currency-aware pricing and cross-region comparison work.
- [Importing your own cost database](./cost-database-import.md) - load your rates from Excel or CSV, as a flat rate sheet or as resource-based assemblies, straight into the cost database.

## Modules

- [Module ecosystem overview](./modules/README.md) - the full module set, grouped by area, with a one-line description each, so you can see the breadth and jump to what you need.

## Build on the platform

For developers extending or building on OpenConstructionERP.

- [Platform and builder guide](./platform/README.md) - the developer story: the module loader, manifests, auto-discovery, events, hooks, and the first-module tutorial.
- [Module development quickstart](./module-development/quickstart.md) - zero to a running module in about ten minutes.
- [BOQ importer plugin walkthrough](./module-development/boq-importer-plugin.md) - a worked example that builds a real import module.
- Live API reference: a running instance publishes an interactive OpenAPI reference at `/docs`, and every module mounts its endpoints under `/api/v1/<module>/`.

## Partner packs

- [Partner packs](./partner-packs/README.md) - code-free preset bundles that brand and pre-configure an install for a region or vertical, setting currency, locale, cost catalogues, validation rules and onboarding.
- [Partner pack manifest reference](./partner-packs/MANIFEST_REFERENCE.md) - every manifest field, with types, defaults and examples.
- [Mullets Aluminum Products deployment profile](../packs/mullets-aluminum/README.md) - the CADcoLabs branch-specific pack, activation paths, verified branding, and current UAT boundary.

## Architecture and decision records

- [Architecture decision records (ADR)](./adr/README.md) - why the platform is built the way it is, including the decision to convert all CAD and BIM through the DDC canonical pipeline rather than parse IFC natively.
- [RFCs](./rfc/README.md) - longer design proposals and the options weighed behind bigger changes.
- [BIM storage architecture](./BIM-STORAGE-ARCHITECTURE.md) - how BIM projects of every size are stored and queried.
- [Field worker mobile design](./architecture/FIELD_WORKER_MOBILE_DESIGN.md) - the design for the on-site mobile experience.

## Install and run

- [Linux install guide](./INSTALL_LINUX.md) - set up on a server.
- [Desktop install guide](./desktop/INSTALL.md) - set up on a workstation.
- [Email and SMTP setup](./email-setup.md) - configure outbound mail for password resets, tender invitations and notifications, pick the right port, and check whether it is working.

## How the platform fits together

Everything reads from and writes to one canonical data layer, so the modules are not islands. A quantity you take off a drawing becomes a BOQ position. That position carries a classification code, a rate from a cost base, and a link back to the model element it came from. The same position feeds the schedule as a 4D activity, the cost model as a 5D cost, and the carbon account as a 6D figure. A validation report scores it, a tender package draws from it, and a report exports it. When you learn one workflow, the next one already speaks the same language.

Two principles run through all of it. First, the platform is open and your data is yours, exportable in open formats such as GAEB XML, Excel and JSON, with no lock-in. Second, where the platform uses AI to suggest a quantity, a classification or a rate, it always shows a confidence score and waits for a person to confirm. Nothing is applied to your estimate automatically.
