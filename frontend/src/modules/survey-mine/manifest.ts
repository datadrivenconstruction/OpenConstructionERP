// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Pickaxe } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/survey/MinePage'));

export const manifest: ModuleManifest = {
  id: 'mine_survey',
  name: 'mine.page.title',
  description: 'mine.module_description',
  version: '0.1.0',
  icon: Pickaxe,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on.
  defaultEnabled: false,
  depends: ['survey_core', 'surfaces_volumes'],
  routes: [{ path: '/survey/mine', title: 'mine.page.title', component: Page }],
  navItems: [{ labelKey: 'mine.page.title', to: '/survey/mine', icon: Pickaxe, group: 'grp_survey' }],
};
