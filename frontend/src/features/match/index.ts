// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

export { MatchSuggestionsPanel } from './MatchSuggestionsPanel';
export type { MatchSuggestionsPanelProps } from './MatchSuggestionsPanel';
export * from './types';
export { acceptMatch, matchElement, submitMatchFeedback } from './api';
export {
  useAcceptMatch,
  useMatchElement,
  useSubmitMatchFeedback,
} from './queries';
