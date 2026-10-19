# Historical benchmarks: predictive estimates (issue #492 P2, proposal for decision, 2026-10-19)

Status: proposal, not built. It needs a decision on scope before any code. Companion to
`historical_benchmarks.md`.

## 1. What it would do

Today the Performance tab and the estimate check answer "what did comparable past projects achieve, and
where does this estimate sit in that range". P2 is the next question: "given this new project's
characteristics, what should this figure be, and how sure are we". Examples: labour hours per m2 for a
330 DIN 276 wall package on a 6-storey residential job in region X, or cost per m2 GFA at the concept
stage before any bill exists.

The first version should stay narrow: one KPI at a time, one predicted value with an interval, for the
same KPIs the benchmark already reads. No new KPI, no model that writes anything.

## 2. Scope options

1. **Explained benchmark (recommended first).** A transparent regression over the benchmark cohort:
   the KPI against a few project attributes the platform already stores (project type, region, size
   such as GFA or bill total, end year, classification code). Ordinary least squares or a robust
   variant on the log of the value, done in Python with no new dependency. Output: predicted value,
   prediction interval, and the coefficient of each attribute, so a person can read why. This is a
   modest step from the current benchmark and reuses its cohort, access rules, unit, currency and cost
   index handling unchanged.
2. **Nearest comparable projects.** Rank the cohort by similarity to the new project and take a
   weighted median of the closest N. Easier to explain than a regression ("these five jobs"), weaker
   with few projects.
3. **Learned model per tenant.** Gradient boosting or similar over many attributes. Better accuracy
   on large histories, but it adds a dependency, training jobs and a model store, and it is hard to
   explain. Not before options 1 or 2 have shown value.

## 3. Data needed

- Enough projects with a value for the KPI: as a floor, ten projects with a value per predicted group,
  and the result must say when it rests on fewer.
- The attributes, filled in: project type, region, GFA or another size measure, start and end dates,
  classification codes on positions. The data quality card already measures some of this; it would
  gain an "attributes filled" share.
- Money brought to one reference month and region (the cost index work in `historical_benchmarks.md`)
  and one currency (FX), or the model learns inflation instead of design.
- For productivity KPIs, hours booked to positions and reported progress; the demo data does this,
  real tenants often do not, which the data quality card shows.

## 4. Risks

- **Small samples.** Most tenants have tens of projects, not thousands. A model fitted on twelve
  projects with five attributes overfits. Mitigation: few attributes, a hard minimum per attribute,
  and an interval that widens honestly; fall back to the plain benchmark when the fit is not better.
- **Leakage and survivorship.** Projects with complete data are not a random sample (finished, well
  run jobs report better). The result must name the cohort and the share of projects excluded.
- **False precision.** A single predicted number reads as an answer. It must always come with the
  interval, the sample size and the comparison with the plain median.
- **Access.** The model must only ever see the projects the caller may open, exactly as the benchmark
  does; a shared, cross-user model would leak other users' projects through its coefficients.
- **Drift.** A model fitted once goes stale as prices and methods change. Fit at request time over the
  current cohort, which is cheap at this scale, instead of storing a model.

## 5. Confidence and human confirmation

Following the platform rule (AI suggests, a person confirms, with confidence scores):

- Every prediction carries a confidence band derived from the data, not a model's self-assessment:
  `low` under ten projects or when the interval is wider than the interquartile range of the plain
  benchmark, `medium` up to thirty projects, `high` above, and never higher than the benchmark's own
  confidence for the same group.
- The prediction is shown beside the plain benchmark (median, P25 to P75) and the estimator's value,
  never in place of them, with the attributes that moved it and by how much.
- Nothing is written. Using a predicted value in an estimate is an explicit action by the estimator
  (for example "apply to this position"), recorded with the prediction's inputs, interval and
  confidence in the position's history, and reversible like any edit.
- An audit line per applied prediction lets a reviewer see later which figures came from a model.

## 6. Questions for the founder

1. Start with option 1 (explained regression) only, behind the same opt-in pattern as the cost index?
2. Which three KPIs matter most for the first version (proposal: cost per m2 GFA at concept stage,
   estimate rate per unit by classification code, labour hours per installed unit)?
3. Is "apply to this position" wanted in the first version, or should it stay read-only until the
   predictions have been compared with outcomes on a few real projects?
