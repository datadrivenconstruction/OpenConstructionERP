import type { FC } from 'react';
import {
  ProjectsGridRenderer,
  BOQRenderer,
  ScheduleRenderer,
  ValidationRenderer,
  CostModelRenderer,
  RiskMatrixRenderer,
  CompareRenderer,
  CWICRRenderer,
  GenericTableRenderer,
} from './renderers';

const RENDERERS: Record<string, FC<{ data: unknown }>> = {
  projects_grid: ProjectsGridRenderer,
  boq_table: BOQRenderer,
  schedule_gantt: ScheduleRenderer,
  validation_list: ValidationRenderer,
  cost_model: CostModelRenderer,
  risk_matrix: RiskMatrixRenderer,
  compare_table: CompareRenderer,
  cwicr_results: CWICRRenderer,
  generic_table: GenericTableRenderer,
};

interface DataPanelRouterProps {
  renderer: string;
  data: unknown;
}

export default function DataPanelRouter({ renderer, data }: DataPanelRouterProps) {
  const Component = RENDERERS[renderer] ?? GenericTableRenderer;
  return <Component data={data} />;
}
