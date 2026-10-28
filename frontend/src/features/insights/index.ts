// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
export { InsightsPanel } from './InsightsPanel';
export { InsightsToggleButton } from './InsightsToggleButton';
export { useModuleInsights, newInsightId } from './useModuleInsights';
export { computeSeries, computeKpi } from './aggregate';
export type {
  Aggregation,
  ChartKind,
  InsightDataset,
  InsightDef,
  InsightField,
  ValueFormat,
} from './types';
