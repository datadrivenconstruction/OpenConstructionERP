// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Moved to shared/lib so a picker outside the BOQ feature can filter and
// highlight by the same rule. Re-exported from the original path because the
// catalogue picker, the assembly picker and the cost-item autocomplete all
// import it from here, and a working import is not worth churning.
export { highlightMatch, foldForSearch } from '@/shared/lib/highlightMatch';
