// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Compliance feature barrel — Natural Language Rule Builder (T13).

export { NlRuleBuilderPanel } from './NlRuleBuilderPanel';
export { DslPreview } from './DslPreview';
export { NlPatternHints } from './NlPatternHints';
export {
  parseNlToDsl,
  listNlPatterns,
  saveDslRule,
  type NlBuildRequest,
  type NlBuildResult,
  type NlPattern,
  type DSLCompileResult,
} from './api';
