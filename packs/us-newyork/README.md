# New York Construction Pack

State depth for New York, layered on top of the US Construction Pack and the
US cost data rather than repeating them. The national pack carries the
classification structures, the owner-contractor agreement family, the progress
payment application and imperial units. This pack carries what changes when a
job is in New York.

## What this pack carries

### Capital improvement or repair

The rate is not the rule that costs money. A capital improvement to real
property is not a taxable service: the customer gives the contractor Form
ST-124, no tax is charged on the contract, and the contractor pays tax on the
materials it buys, with no credit. A repair, maintenance or installation job is
taxed on the whole charge, labor included, at the combined rate of the jobsite.

Worked example, 8.875 percent New York City combined rate, 400,000 dollars of
materials and 800,000 of labor: as a capital improvement the contractor pays
35,500 dollars on materials and charges nothing; as a repair the customer is
charged 106,500 dollars on the whole bill.

The state rate is 4 percent. Counties and cities add their own, so the
combined rate is a property of the address; the pack warns when an estimate
uses the state rate alone.

### Prevailing wage and certified payroll

Public work pays the Article 8 prevailing rate from a schedule issued by the
state labor department, or by the city Comptroller inside New York City.
Certified payroll is filed electronically; the platform exports the
department's `ProjectRollup` XML for a person to upload, and names every field
the week does not hold (the project registration code, worker addresses).

A private project over 5 million dollars paid for at least 30 percent with
public funds is a covered project under Labor Law § 224-a.

### Retainage

Private contracts of 150 thousand dollars or more entered into on or after
17 November 2023 hold no more than 5 percent of each payment, down the whole
chain (General Business Law § 756-c); a clause above the cap is void (§ 757).
Public owners hold no more than 5 percent.

Worked example: 10 percent held on a 250,000 dollar payment exceeds the cap
of 12,500.

### Payment and lien clocks

The state, local and private payment clocks are seeded as payment clock
regimes. A notice of lien is filed within 8 months of the last work, or 4
months for a single family dwelling (Lien Law § 10). Last work on 15 December
2026 gives 15 August 2027, or 15 April 2027 for a single family home.

## Demo project

Grand Concourse Residences, a nine-storey, 112-unit rental building in the
Bronx, designed to the 2022 New York City Building Code, priced in US
customary units.

## Not legal advice

Every deadline and limit is computed from the statute cited beside it. Verify
every date with counsel before relying on it.

## Open items

- The covered private project threshold under § 224-a is carried as a rule but
  not yet checked automatically; the share of public funds is not a project
  field today.
