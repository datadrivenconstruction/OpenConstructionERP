# openconstructionerp-hongkong-hk

Country pack for Hong Kong SAR. It sets up the workspace the way a Hong Kong quantity surveyor or main contractor works:

- **Payment claims on the Cap. 652 clock.** The `hk_sopo` payment regime gives each valuation its statutory dates: payment response, payment, the day a dispute arises and the last day to serve the adjudication notice.
- **Two statutory levies.** The CIC levy (0.5 percent) and the CWR levy (0.03 percent) are added to works over HK$3,000,000.
- **No tax line.** Hong Kong has no VAT or GST.
- **Retention defaults.** Retention is 10 percent of each valuation, up to 5 percent of the contract sum.
- **HKSMM4 codes.** Bills are coded to an HKSMM4 section skeleton.
- **ArchSD indices.** The tender price indices from the Architectural Services Department are included for escalation.
- **Interface languages.** Traditional Chinese (Hong Kong) and English (Hong Kong).

## What the pack sets

| Area | Value | Source |
|---|---|---|
| Currency | HKD, 2 decimals | ISO 4217 |
| Payment regime | `hk_sopo` (see below) | Cap. 652 |
| Levies | CIC 0.5 %, CWR 0.03 %, on works over HK$3,000,000 (from 30.07.2018) | Cap. 587, Cap. 583, cic.hk |
| Tax | none | no VAT or GST in Hong Kong |
| Retention | 10 % of each valuation, limit 5 % of the contract sum | working default, GCC cl. 79 is the retention clause; figures not verified, never enforced |
| Contract forms | GCC Building Works 1999 (public), NEC4 ECC (public, common), HKIA/HKICM/HKIS private form | names only, no clause text |
| Classification | HKSMM4 code skeleton, `data/hksmm4_skeleton.json` | codes and our own descriptions only |
| Price indices | BWTPI (1970 Q1 = 100), BSTPI (1989 Q4 = 100), `data/archsd_tpi.json` | DATA.GOV.HK, ArchSD |
| Validation | rule set `hongkong` (13 rules), compliance pack `hk_compliance` | |
| Demo | `hk-gov-office-fitout`, HK$50M government office fit-out, contract made 01.02.2026 | |

## Security of Payment Ordinance (Cap. 652)

These rules come from the text of the Ordinance itself, not from secondary summaries.

- **Scope (s.4 to s.7, Schedule 4).**
  - The Ordinance covers contracts made on or after 28 August 2025.
  - For public contracts, it covers works of HK$5,000,000 or more, or goods and services only of HK$500,000 or more.
  - A private main contract is covered only for new buildings, or for works that need Building Authority approval under Cap. 123 s.14(1). The rule `hk.sopo.private_scope_check` asks the user to confirm this. Nothing is assumed.
  - A subcontract is covered at any value when its main contract is covered.
- **Payment response (s.20).**
  - The response is due by the earlier of two dates: the date the contract sets, and 30 days after the claim is served.
  - A claim served before the billing date is taken to be served on the billing date (s.18). In the clock, the valuation's period end acts as the billing date.
- **Payment (s.15).** Payment is due by the earlier of the contract date and 60 days after the claim.
- **No response (s.21).** If no response is served, the claimed amount is in dispute, and set-off cannot be raised at adjudication.
- **Adjudication (s.23, s.24).**
  - The dispute arises on the day after the response deadline.
  - The notice of adjudication must be served within 28 days, counting that day as day one.
  - Worked example: response due 30.04.2026, dispute arises 01.05.2026, notice due by 28.05.2026.
- **Conditional payment (s.12).** A pay-when-paid clause has no effect. Contracts record such a clause with the `pay_when_paid` flag, and rule `hk.contract.pay_when_paid` reports it.

## Price indices and attribution

The Architectural Services Department publishes BWTPI and BSTPI on DATA.GOV.HK. The DATA.GOV.HK Terms and Conditions of Use allow free use, including commercial use and redistribution. Attribution is required, and the Government keeps the intellectual property.

The snapshot in `data/archsd_tpi.json` carries the attribution on each series. If you load fresh figures, use `POST /api/v1/price-index/import/quarterly/`. That import refuses any series without an attribution.

Quarters the publisher marks "-" or "Not Available" are left out.

> Source: Architectural Services Department, HKSAR Government, via DATA.GOV.HK.

## HKSMM4

HKSMM4 is published by the Hong Kong Institute of Surveyors and is copyrighted. The pack ships section codes with our own short descriptions, never the method text. The section order and numbering are pending confirmation against the publication.

## Locales

- **`zh-HK`.** The interface in Traditional Chinese (Hong Kong). The browser tags `zh-HK`, `zh-MO`, `zh-TW` and `zh-Hant` resolve to it. A Traditional Chinese browser is never served Simplified Chinese. A missing key falls back to English. Users can switch language at any time.
- **`en-HK`.** British English with the Hong Kong terms.

The core zh-HK bundle was seeded from the Simplified bundle in three steps:

1. Conversion to Traditional characters with the Hong Kong variant table.
2. Replacement of the construction and software terms with the Hong Kong terms in the glossary below.
3. English for every key with no Chinese source.

No native speaker has reviewed it yet.

## Glossary for review (Hong Kong usage)

Each row gives the Hong Kong term, the English term, and the term used in Taiwan or the mainland that we avoid. **Status: every row is pending review by a Hong Kong quantity surveyor.**

| Hong Kong | English | Avoided |
|---|---|---|
| 工料清單 | bills of quantities | 工程數量表, 工程量清單 |
| 工料測量師 | quantity surveyor | 估價師, 造價工程師 |
| 承建商 | contractor | 營造廠, 承包商 |
| 總承建商 | main contractor | 總承包商 |
| 指定分包商 | nominated subcontractor | 協力廠商 |
| 地盤 | site | 工地 |
| 地盤總管 | site agent | 工地主任 |
| 開辦費 | preliminaries | 共同項目, 假設工程 |
| 主要成本金額 | prime cost sum | 指定金額 |
| 暫定金額 | provisional sum | 暫列金額 |
| 計日工 | daywork | 點工 |
| 單價 | unit rate | |
| 度尺 | take-off | 數量計算, 算量 |
| 中期付款 | interim payment | 估驗計價 |
| 保留金 | retention | 保留款 |
| 最終結算 | final account | 結算 |
| 實際竣工 | practical completion | 完工 |
| 保養期 | defects liability period | 保固期, 缺陷責任期 |
| 違約賠償金 | liquidated damages | 逾期違約金 |
| 延長工期 | extension of time | 展延工期 |
| 更改工程 | variation | 契約變更 |
| 建築師指示 | architect's instruction | 監造指示 |
| 投標 | tender | |
| 合約金額 | contract sum | 契約金額 |
| 付款申索 | payment claim | 請款 |
| 付款回應 | payment response | |
| 審裁 | adjudication | 爭議審議 |
| 棚架 | scaffolding | 鷹架, 腳手架 |
| 項目 | project | 專案 |
| 建造業議會徵款 | CIC levy | |
| 強積金 | MPF | |
| 圖則 | drawings | 圖紙 |
| 上載 / 匯出 / 匯入 | upload / export / import | 上傳 / 導出 / 導入 |

## Not in this pack

- **HKSMM4, GCC, NEC4 and HKIA/HKICM text.** These are copyrighted, so the pack has codes and names only.
- **Profits tax.** It is not an estimating item.
- **MPF.** It is payroll, never a bill line.
- **BEAM Plus scoring.** The pack gives a reference link only.
- **Client forms.** One client's own forms are configuration, not part of the pack.
- **A zh-TW locale.** It uses different terms and is triaged separately.

## Review status

| Item | Status |
|---|---|
| Periods and thresholds | Read from the Ordinance. Pending review by a Hong Kong construction lawyer. |
| Retention figures | Working defaults. Not verified. |
| NEC4 default | Working default. Not verified. |
| zh-HK wording | Pending review by a Hong Kong quantity surveyor. |
| Glossary | Pending review by a Hong Kong quantity surveyor. |

Do not rely on this pack for a tender or a claim before that review.
