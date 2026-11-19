// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Calculator, Crosshair } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/survey/SurveyRegisterPage'));
const CalcPage = lazy(() => import('@/features/survey-calc/CalcPage'));

export const manifest: ModuleManifest = {
  id: 'survey_core',
  name: 'survey.page.register',
  description: 'survey.module_description',
  version: '0.1.0',
  icon: Crosshair,
  category: 'tools',
  // Off until a survey focus profile or Settings > Modules turns it on, so the
  // Survey & Land group stays out of menus that have no use for it.
  defaultEnabled: false,
  depends: [],
  routes: [
    { path: '/survey', title: 'survey.page.register', component: Page },
    { path: '/survey/calc', title: 'survey.cogo.title', component: CalcPage },
  ],
  navItems: [
    { labelKey: 'survey.page.register', to: '/survey', icon: Crosshair, group: 'grp_survey' },
    { labelKey: 'survey.cogo.title', to: '/survey/calc', icon: Calculator, group: 'grp_survey' },
  ],
};
