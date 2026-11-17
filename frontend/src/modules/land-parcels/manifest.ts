// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { LandPlot } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/land-parcels/LandParcelsPage'));

export const manifest: ModuleManifest = {
  id: 'land-parcels',
  name: 'survey.parcels.title',
  description: 'survey.parcels.module_description',
  version: '0.1.0',
  icon: LandPlot,
  category: 'tools',
  // Off until a survey or developer profile turns it on: land is the owner's work, so most menus never show it.
  defaultEnabled: false,
  depends: [],
  routes: [{ path: '/survey/parcels', title: 'survey.parcels.title', component: Page }],
  navItems: [{ labelKey: 'survey.parcels.title', to: '/survey/parcels', icon: LandPlot, group: 'grp_survey' }],
};
