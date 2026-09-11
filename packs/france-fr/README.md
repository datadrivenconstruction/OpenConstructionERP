# France Construction Pack

A country pack for French construction work. It configures the workspace
around the way a French estimate is built: a DPGF decomposition priced in
euros, measured to the NF DTU series, and subject to the regulatory framework
that governs public and private construction in France.

## What makes a French estimate French

The central document in French construction pricing is the DPGF, the
Decomposition du Prix Global et Forfaitaire. It breaks a lump-sum price into
its constituent parts so that the client can read what is inside the number.
Alongside it sits the CCTP, the Cahier des Clauses Techniques Particulieres,
which specifies the technical requirements for each lot. Together they form the
pricing and specification pair that every French tender carries.

Measurement follows the NF DTU series, the collection of technical standards
published by AFNOR and the CSTB that define how building works are specified
and measured. Each trade has its own DTU, and an estimate that measures outside
the DTU for that trade cannot be checked against the standard the contract
assumes.

French public procurement is governed by the Code des marches publics, which
sets the rules for how public works are tendered, evaluated and awarded. The
CCAG-Travaux provides the general conditions for public works contracts.
Private works follow the Loi MOP framework for project management.

The RE 2020 regulation, which replaced RT 2012, sets the energy and
environmental performance requirements for new buildings. It affects cost
through insulation, HVAC and renewable energy provisions.

## What this pack enables

- **Currency EUR**, the `fr_tva_20` tax template and DPGF as the
  classification standard, with a French-language interface.
- **One engine rule set**, `dpgf`, which validates that priced lines carry
  the decomposition structure the standard expects.
- **Two demo projects**, `school-paris` and `hospital-lyon`, showing a
  public school and a hospital project priced in the DPGF format.
- **A three-step onboarding wizard** that collects the company profile
  including SIRET, confirms the standards in use, and reviews the setup.

## Standards referenced

- Code des marches publics (public procurement code)
- NF DTU series (AFNOR/CSTB technical standards)
- Loi MOP (project management framework for public works)
- CCAG-Travaux (general conditions for public works contracts)
- RE 2020 (energy and environmental performance regulation)
- DPGF (Decomposition du Prix Global et Forfaitaire)
- CCTP (Cahier des Clauses Techniques Particulieres)

These are referenced for interoperability and compliance checking. Clause
and section numbers are interoperability facts and are used as such; the
publishers' own text and tables are not reproduced here.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "France Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=france-fr openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
