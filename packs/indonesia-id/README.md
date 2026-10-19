# Indonesia Construction Pack

Configures OpenConstructionERP for the Indonesian construction market. Estimating
in Indonesia follows the AHSP (Analisa Harga Satuan Pekerjaan) unit rate analysis
method, where every work item is built up from its material, labour and equipment
components against SNI standards. Currency is IDR with 11% PPN on construction
services.

## What makes an Indonesian estimate Indonesian

A RAB (Rencana Anggaran Biaya, project cost plan) in Indonesia is structured as a
detailed unit rate analysis. Each work item carries an AHSP breakdown showing the
material quantities, labour coefficients and equipment hours that make up its unit
rate, referenced against SNI (Standar Nasional Indonesia) standards. The unit rate
analysis is not just documentation - it is how the price is built, and a RAB
without AHSP breakdowns is not a RAB a government client can evaluate.

Public procurement follows Perpres 16/2018 (Presidential Regulation on Government
Procurement of Goods and Services) administered through the LKPP (Lembaga Kebijakan
Pengadaan Barang/Jasa Pemerintah). Construction services are regulated under UU
No. 2/2017 (Jasa Konstruksi). The Kementerian PUPR (Ministry of Public Works and
Housing) publishes the AHSP reference coefficients and regional price indices.

PPN (Pajak Pertambahan Nilai, VAT) on construction services is 11 percent. The
pack does not set it.

## What this pack enables

- **Currency IDR** (the pack does not set PPN) and the `indonesia`
  estimating methodology
- **MasterFormat rule set** for classification validation, as the nearest
  supported hierarchy Indonesian AHSP-structured works map onto
- **Two demo projects**: a commercial tower in Jakarta and a residential
  development in Surabaya, both priced at Indonesian 2026 market rates in IDR
  excluding PPN
- **AHSP, SNI, PUPR and procurement regulatory references** in the pack metadata

## Standards referenced

- AHSP (Analisa Harga Satuan Pekerjaan, unit rate analysis)
- SNI (Standar Nasional Indonesia, national construction standards)
- Peraturan Menteri PUPR (Minister of Public Works regulations)
- UU No. 2/2017 tentang Jasa Konstruksi (Construction Services Act)
- Perpres 16/2018 tentang Pengadaan Barang/Jasa Pemerintah (Public Procurement)
- LKPP (Lembaga Kebijakan Pengadaan Barang/Jasa Pemerintah)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Indonesia Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=indonesia-id openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
