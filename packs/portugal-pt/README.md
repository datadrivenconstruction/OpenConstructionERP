# Portugal Construction Pack

Configures OpenConstructionERP for the Portuguese construction market. Estimating
practice in Portugal is structured around the orcamento (budget), with ProNIC
providing the national classification and specification framework for public
works. Currency is EUR with 23% IVA on construction services.

## What makes a Portuguese estimate Portuguese

A Portuguese orcamento (construction budget) for public works follows ProNIC
(Protocolo para a Normalizacao da Informacao Tecnica na Construcao), which
provides both a classification system and standard technical specifications.
ProNIC organises works into chapters and articles, and a public tender document
(caderno de encargos) that does not reference ProNIC codes is increasingly
unusual for works above the threshold.

Public procurement follows the Codigo dos Contratos Publicos (DL 18/2008),
which transposes the EU directives and governs the tendering process. Building
regulations are set by the RGEU (Regulamento Geral das Edificacoes Urbanas) and
the energy performance framework RCCTE/SCE. Structural design follows the NP EN
Eurocodes (Portuguese adoption).

IVA (Imposto sobre o Valor Acrescentado, VAT) on construction services is 23
percent at the standard rate, with a reduced 6 percent rate applying to certain
renovation and social housing works. The pack does not set IVA.

## What this pack enables

- **Currency EUR** (the pack does not set VAT) and the `portugal`
  estimating methodology
- **MasterFormat rule set** for classification validation, as the nearest
  supported hierarchy Portuguese ProNIC-structured bills map onto
- **Two demo projects**: an office building in Lisbon and a residential
  development in Porto, both priced at Portuguese 2026 market rates in EUR
  excluding IVA
- **ProNIC, CCP and LNEC regulatory references** in the pack metadata

## Standards referenced

- ProNIC (Protocolo para a Normalizacao da Informacao Tecnica na Construcao)
- Codigo dos Contratos Publicos (DL 18/2008)
- RGEU (Regulamento Geral das Edificacoes Urbanas)
- RCCTE/SCE (Regulamento das Caracteristicas de Comportamento Termico)
- NP EN Eurocodes (Portuguese adoption of European structural standards)
- LNEC (Laboratorio Nacional de Engenharia Civil)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Portugal Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=portugal-pt openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
