# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic response schemas for the value-realized API.

Money and rates are carried on the wire as strings (the Decimal rendered
losslessly) per the platform money-as-string convention, so the read models are
built explicitly in the router rather than validated straight off the engine
dataclasses. The currency-independent headlines (hours saved, the dispute-risk
proxy) are the only cross-currency figures and carry no single-currency money.
"""

from __future__ import annotations

from pydantic import BaseModel


class CurrencyValueOut(BaseModel):
    """The money side of a value summary, scoped to one currency (never blended).

    ``recovery_rate`` is a fraction in ``[0, 1]`` rendered as a string (or null
    when nothing was chargeable). ``schedule_days_managed`` is a programme figure
    kept beside the money, never folded into it.
    """

    currency: str
    overrun_exposure_managed: str
    chargeable_total: str
    recovered_total: str
    absorbed_total: str
    recovery_rate: str | None
    schedule_days_managed: str
    impact_count: int
    recovery_item_count: int


class ValueSummaryOut(BaseModel):
    """A project's (or portfolio's) composed value-realized position.

    The money lives in :attr:`by_currency` (one row per currency, never blended).
    The currency-independent headlines are ``estimated_hours_saved`` (hours, two
    places, as a string) and ``dispute_risk_reduction`` (a documented proxy in
    ``[0, 1]`` as a string, or null). Each headline carries a confidence label
    (``high`` / ``medium`` / ``low`` / ``none``) reflecting only how much
    evidence stands behind it.
    """

    project_id: str | None = None
    by_currency: list[CurrencyValueOut]
    primary_currency: str
    estimated_hours_saved: str
    dispute_risk_reduction: str | None
    exposure_confidence: str
    recovery_confidence: str
    hours_confidence: str
    risk_confidence: str
    cost_position_percentile: float | None
    impact_count: int
    recovery_item_count: int
    hours_sample: int
    activity_count: int


class HoursSavedBucketOut(BaseModel):
    """Hours saved for one grouping key (a user, project, feature or period)."""

    key: str
    event_count: int
    unit_count: int
    minutes: str
    hours: str


class HoursSavedOut(BaseModel):
    """Estimated admin hours given back, totalled and grouped on one axis.

    ``by`` echoes the grouping axis used (``user`` / ``project`` / ``feature`` /
    ``period``); ``total_hours`` is the single headline (two places, as a
    string) and reconciles with the sum of the per-bucket minutes.
    """

    project_id: str
    by: str
    total_hours: str
    event_count: int
    buckets: list[HoursSavedBucketOut]


class ProjectScoreOut(BaseModel):
    """One project's adoption score and the cohort it falls in."""

    project_id: str
    adoption: float
    cohort: str


class CohortComparisonOut(BaseModel):
    """High-vs-low adoption comparison on one outcome metric.

    ``high_mean`` / ``low_mean`` / ``delta`` are unitless rates or durations (not
    money) reported as floats, or null when a cohort had no value for the metric.
    ``favours_high`` records whether the delta's sign favours the adopters under
    the metric's better-direction (null on a tie or a missing delta).
    """

    metric: str
    high_mean: float | None
    low_mean: float | None
    delta: float | None
    high_n: int
    low_n: int
    higher_is_better: bool
    favours_high: bool | None
    confidence: str


class AdoptionBenchmarkOut(BaseModel):
    """The portfolio's adoption benchmark: per-project scores + comparisons.

    ``confidence`` is the overall confidence (the weakest comparison's).
    ``high_count`` / ``low_count`` are how many projects fell in each cohort.
    """

    project_scores: list[ProjectScoreOut]
    comparisons: list[CohortComparisonOut]
    confidence: str
    high_count: int
    low_count: int


class AdoptionStepOut(BaseModel):
    """One first-value step and whether the project has reached it.

    ``key`` is the stable step identifier, ``label`` a short human description,
    ``module`` the platform area it belongs to (for grouping), and ``done``
    whether the project's present state satisfies the step.
    """

    key: str
    label: str
    module: str
    done: bool


class AdoptionChecklistOut(BaseModel):
    """A project's guided adoption checklist for one role.

    ``adoption_score`` is the weighted percent (0-100) of the role's applicable
    steps that are done. ``steps`` is every applicable step in onboarding order
    with its done flag; ``next_actions`` is the leading incomplete steps - the
    concrete "do these next" nudge - so they always carry ``done = false``.
    """

    project_id: str
    role: str
    adoption_score: int
    steps: list[AdoptionStepOut]
    next_actions: list[AdoptionStepOut]


class TimeFactorOut(BaseModel):
    """One editable hours-saved minute factor and its provenance.

    ``minutes`` is the value currently in force (the admin override when set,
    else the seed default), as a string so the Decimal is carried losslessly -
    these are minutes of saved effort, never money. ``default_minutes`` is the
    seed default for the pair (null for a tenant-only pair the seed map does not
    define). ``is_override`` is true when the tenant has tuned the pair away from
    the default.
    """

    module: str
    action: str
    minutes: str
    default_minutes: str | None
    is_override: bool


class TimeFactorsOut(BaseModel):
    """The full editable surface of a tenant's hours-saved minute factors."""

    factors: list[TimeFactorOut]


class TimeFactorUpdate(BaseModel):
    """One requested factor override: the pair and its new minute value.

    ``minutes`` is accepted as a string (the lossless money/Decimal convention,
    applied here to minutes) and validated server-side as a finite, non-negative,
    capped value. Setting it equal to the seed default clears the override so the
    pair reverts to inheriting the default.
    """

    module: str
    action: str
    minutes: str


class TimeFactorsUpdate(BaseModel):
    """A batch of factor overrides to apply for the caller's tenant."""

    factors: list[TimeFactorUpdate]
