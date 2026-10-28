// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /match-elements — entry point.
//
// The page is now a guided, multi-step wizard (see MatchWizardFlow):
// Project → Source model → Cost catalogue → Scope & rules → Grouping →
// Run match → Review → Apply. One canonical step rail, one focused
// panel per stage, live counts, plain-language explanations, Back/Next
// + per-stage adjustment, and a final dry-run-then-write BOQ rollup.
// It drives the real backend pipeline end-to-end (BIM elements → CWICR
// cost-code candidates with scores → BOQ). The route and the
// ``MatchElementsPage`` named export are unchanged so app routing and
// lazy imports keep working without edits elsewhere.

export { MatchWizardFlow as MatchElementsPage } from './MatchWizardFlow';
