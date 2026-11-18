// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Target } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/setting-out/SettingOutPage'));

export const manifest: ModuleManifest = {
  id: 'setting-out',
  name: 'survey.page.setting_out',
  description: 'survey.setting_out.module_description',
  version: '0.1.0',
  icon: Target,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on.
  defaultEnabled: false,
  depends: ['survey_core'],
  routes: [{ path: '/survey/setting-out', title: 'survey.page.setting_out', component: Page }],
  navItems: [{ labelKey: 'survey.page.setting_out', to: '/survey/setting-out', icon: Target, group: 'grp_survey' }],
};
