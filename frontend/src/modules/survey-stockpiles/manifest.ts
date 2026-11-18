// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Warehouse } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/survey/StockpilesPage'));

export const manifest: ModuleManifest = {
  id: 'stockpiles',
  name: 'stockpiles.page.title',
  description: 'stockpiles.module_description',
  version: '0.1.0',
  icon: Warehouse,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on.
  defaultEnabled: false,
  depends: ['survey_core', 'surfaces_volumes'],
  routes: [{ path: '/survey/stockpiles', title: 'stockpiles.page.title', component: Page }],
  navItems: [{ labelKey: 'stockpiles.page.title', to: '/survey/stockpiles', icon: Warehouse, group: 'grp_survey' }],
};
