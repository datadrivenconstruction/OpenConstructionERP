// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Mountain } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/survey/VolumesPage'));

export const manifest: ModuleManifest = {
  id: 'surfaces_volumes',
  name: 'volumes.page.title',
  description: 'volumes.module_description',
  version: '0.1.0',
  icon: Mountain,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on.
  defaultEnabled: false,
  depends: ['survey_core'],
  routes: [{ path: '/survey/volumes', title: 'volumes.page.title', component: Page }],
  navItems: [{ labelKey: 'volumes.page.title', to: '/survey/volumes', icon: Mountain, group: 'grp_survey' }],
};
