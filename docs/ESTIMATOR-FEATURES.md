# What Every Real Estimator Needs — Feature Analysis

## Daily Workflow of a Construction Cost Estimator

```
1. Receive scope (drawings, specs, tender docs)
2. Study the project (type, location, complexity)
3. Create cost structure (by trades, by elements, by phases)
4. Measure quantities (from drawings / BIM / site visit)
5. Price each item (from database + quotes + experience)
6. Apply markups (overhead, profit, risk, inflation)
7. Compare with benchmarks (cost/m², similar projects)
8. Review and adjust (value engineering, alternatives)
9. Generate reports (for client, for management, for tender)
10. Track changes (during construction: variations, claims)
```

## Missing Features (Priority Order)

### P0 — Without these, no estimator will use the tool

#### 1. BOQ SECTIONS WITH SUBTOTALS
Every real estimate has sections. Not a flat list.
```
01. Erdarbeiten                              Subtotal: 127,625.00
  01.01.0010  Baugrube ausheben       2,850 m³ × 12.50 =  35,625.00
  01.01.0020  Bodenabtransport        1,900 m³ × 18.00 =  34,200.00
  01.01.0030  Verbau Baugrube           680 m² × 85.00 =  57,800.00

02. Beton- und Stahlbetonarbeiten            Subtotal: 786,300.00
  02.01.0010  Bodenplatte               420 m³ × 285.00 = 119,700.00
  ...

═══════════════════════════════════════ GRAND TOTAL: 1,666,875.00
```
Currently: flat list, no sections, no subtotals.
Need: parent positions = sections, child positions = items, auto subtotals.

#### 2. COST BREAKDOWN (Material / Labor / Equipment / Subcontractor)
Every estimator breaks down every rate:
```
Position: Stahlbeton Wand C30/37, d=25cm        Rate: 350.00 EUR/m³
  ├── Material:    Beton C30/37 supply          165.00 EUR/m³  (47%)
  ├── Labor:       Betonarbeiter, 2 Mann        120.00 EUR/m³  (34%)
  ├── Equipment:   Kran, Schalung               45.00 EUR/m³  (13%)
  └── Subcontract: Bewehrung verlegen           20.00 EUR/m³   (6%)
```

#### 3. MARKUP & OVERHEAD SYSTEM
Every tender has markups on top of direct costs:
```
Direct Costs (Einzelkosten der Teilleistungen):     1,200,000.00
+ Site Overhead (Baustellengemeinkosten BGK):  8%      96,000.00
= Total Site Cost:                                  1,296,000.00
+ Company Overhead (Allgemeine Geschäftskosten AGK): 5% 64,800.00
+ Profit (Wagnis und Gewinn W&G):              3%      38,880.00
= Net Tender Sum:                                   1,399,680.00
+ VAT/Tax:                                    19%     265,939.20
= Gross Tender Sum:                                 1,665,619.20
```

Different regions use different markup structures:
- Germany: EKT + BGK + AGK + W&G
- UK: Preliminaries + OH&P + Contingency
- US: General Conditions + OH&P + Contingency + Escalation + Bond
- Russia: Накладные расходы + Сметная прибыль + НДС

#### 4. BENCHMARK COMPARISON
Compare your estimate against known benchmarks:
```
Project: Wohnanlage Berlin-Mitte
  Your estimate:    2,155 EUR/m² GFA
  BKI benchmark:    2,200-2,600 EUR/m² (Mehrfamilienhaus, Berlin)
  Status:           ⚠️ Below range — check scope completeness
```

### P1 — Critical for professional use

#### 5. ESTIMATE VERSIONS & COMPARISON
Track how the estimate evolves:
```
Version 1 (Concept):     8,500,000 EUR   (Feb 2026)
Version 2 (Detailed):   12,500,000 EUR   (Mar 2026)  +47%
Version 3 (Final):      11,800,000 EUR   (Apr 2026)  -5.6%
Version 4 (As-built):   12,100,000 EUR   (Dec 2027)  +2.5%
```
Delta report: which positions changed, by how much.

#### 6. ALTERNATES / VALUE ENGINEERING
"What if we use cheaper material?"
```
Base case:     Naturstein Fassade     → 850,000 EUR
Alternate A:   Klinker Fassade        → 520,000 EUR  (saves 330,000)
Alternate B:   Wärmedämmverbund       → 380,000 EUR  (saves 470,000)
```

#### 7. SUBCONTRACTOR QUOTE MANAGEMENT
Collect and compare quotes from subcontractors:
```
Trade: Elektro
  Quote 1: Elektro Schmidt GmbH      420,000 EUR
  Quote 2: Müller Elektrotechnik     385,000 EUR  ← lowest
  Quote 3: Elektro Weber             395,000 EUR
  Budget estimate:                    410,000 EUR
```

#### 8. RISK/CONTINGENCY ANALYSIS
```
Risk Register:
  Ground conditions uncertainty:     5%  on Erdarbeiten     →  6,381 EUR
  Material price volatility:         3%  on Materials        → 15,200 EUR
  Weather delays:                    2%  on all              → 33,338 EUR
  Design changes:                    5%  on all              → 83,344 EUR
                                              Total Risk: 138,263 EUR
```

### P2 — Differentiators

#### 9. PRODUCTIVITY RATES
Labor output varies by region:
```
Mauerwerk KS d=24cm:
  Germany:    0.85 h/m²   (38.25 EUR/h = 32.51 EUR/m²)
  Poland:     0.75 h/m²   (22.00 EUR/h = 16.50 EUR/m²)
  UAE:        0.95 h/m²   (12.00 USD/h = 11.40 USD/m²)
```

#### 10. TAX & REGULATORY
Different tax structures worldwide:
- Germany: 19% MwSt
- UK: 20% VAT (some items 0%)
- UAE: 5% VAT
- US: varies by state (sales tax on materials only)
- Russia: 20% НДС
- India: 18% GST

#### 11. CLAIMS & VARIATIONS
During construction, scope changes:
```
Variation Order #7:
  Original: 420 m³ Beton Bodenplatte
  Actual:   485 m³ (+65 m³, +15.5%)
  Cost impact: +18,525 EUR
  Status: Submitted → Under Review → Approved/Rejected
```

#### 12. IMPORT FROM EXTERNAL SYSTEMS
- Excel spreadsheet (universal)
- GAEB XML X81-X89 (Germany)
- PDF OCR extraction
- MS Project (schedule)
- Primavera P6 (schedule)
- SAP integration

## Implementation Priority for Maximum Impact

### Sprint 1 (NOW): BOQ Sections + Subtotals + Markups
This alone makes the tool usable by real estimators.

### Sprint 2: Cost Breakdown + Benchmarks
Makes estimates defensible and professional.

### Sprint 3: Versions + Alternatives + Quotes
Makes it a real project management tool.

### Sprint 4: Risk + Claims + Regional specifics
Makes it enterprise-ready.
