// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
export { QuickEstimatePage } from './QuickEstimatePage';
export {
  EXAMPLE_PROMPTS,
  getExamplePromptById,
  type ExamplePrompt,
} from './examplePrompts';
export {
  useQuickEstimateHistory,
  historyStorageKey,
  readHistory,
  writeHistory,
  lruInsert,
  HISTORY_MAX,
  HISTORY_SCHEMA_VERSION,
  HISTORY_KEY_PREFIX,
  type HistoryEntry,
  type HistoryStatus,
  type UseQuickEstimateHistory,
} from './useQuickEstimateHistory';
