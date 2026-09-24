// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
export { default as BOQRenderer } from './BOQRenderer';
export { default as ValidationRenderer } from './ValidationRenderer';
export { default as ProjectsGridRenderer } from './ProjectsGridRenderer';
export { default as ScheduleRenderer } from './ScheduleRenderer';
export { default as CostModelRenderer } from './CostModelRenderer';
export { default as RiskMatrixRenderer } from './RiskMatrixRenderer';
export { default as CompareRenderer } from './CompareRenderer';
export { default as CWICRRenderer } from './CWICRRenderer';
export { default as GenericTableRenderer } from './GenericTableRenderer';
export { default as ProjectSummaryRenderer } from './ProjectSummaryRenderer';
export { default as SemanticSearchRenderer } from './SemanticSearchRenderer';
export { default as BOQItemCreatedRenderer } from './BOQItemCreatedRenderer';

// Canonical map from backend `renderer` names (emitted by the tool handlers
// in backend/app/modules/erp_chat/tools.py) to the React component. Used by
// both the /chat data panel (DataPanelRouter) and the floating chat panel so
// the two surfaces never drift. Aliases cover legacy renderer names that
// older persisted ChatMessage rows may still carry.
import type { FC } from 'react';
import BOQRendererC from './BOQRenderer';
import ValidationRendererC from './ValidationRenderer';
import ProjectsGridRendererC from './ProjectsGridRenderer';
import ScheduleRendererC from './ScheduleRenderer';
import CostModelRendererC from './CostModelRenderer';
import RiskMatrixRendererC from './RiskMatrixRenderer';
import CompareRendererC from './CompareRenderer';
import CWICRRendererC from './CWICRRenderer';
import GenericTableRendererC from './GenericTableRenderer';
import ProjectSummaryRendererC from './ProjectSummaryRenderer';
import SemanticSearchRendererC from './SemanticSearchRenderer';
import BOQItemCreatedRendererC from './BOQItemCreatedRenderer';
import { ActionProposalRenderer } from '../../../actions/ActionProposalCard';

export const RENDERER_REGISTRY: Record<string, FC<{ data: unknown }>> = {
  // Backend renderer names (the source of truth).
  projects_grid: ProjectsGridRendererC,
  project_summary: ProjectSummaryRendererC,
  boq_table: BOQRendererC,
  schedule_gantt: ScheduleRendererC,
  validation_dashboard: ValidationRendererC,
  risk_register: RiskMatrixRendererC,
  cost_items_table: CWICRRendererC,
  cost_model: CostModelRendererC,
  project_comparison: CompareRendererC,
  boq_item_created: BOQItemCreatedRendererC,
  // A proposed change waiting for a person to apply it (erp_chat propose_* tools).
  action_proposal: ActionProposalRenderer,
  semantic_search: SemanticSearchRendererC,
  generic_table: GenericTableRendererC,
  // Legacy aliases (kept so old persisted messages keep rendering).
  validation_list: ValidationRendererC,
  risk_matrix: RiskMatrixRendererC,
  cwicr_results: CWICRRendererC,
  compare_table: CompareRendererC,
};
