// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Activity } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/monitoring/MonitoringPage'));

export const manifest: ModuleManifest = {
  id: 'monitoring',
  name: 'survey.page.monitoring',
  description: 'survey.monitoring.module_description',
  version: '0.1.0',
  icon: Activity,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on.
  defaultEnabled: false,
  depends: ['survey_core'],
  routes: [{ path: '/survey/monitoring', title: 'survey.page.monitoring', component: Page }],
  navItems: [{ labelKey: 'survey.page.monitoring', to: '/survey/monitoring', icon: Activity, group: 'grp_survey' }],
};
