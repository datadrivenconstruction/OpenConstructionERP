// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Calculator, Compass, Crosshair, PenTool } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/survey/SurveyRegisterPage'));
const Hub = lazy(() => import('@/features/survey/SurveyHubPage'));
const Setup = lazy(() => import('@/features/survey/SurveyHubPage').then((m) => ({ default: m.SurveySetupPage })));
const PlanPage = lazy(() => import('@/features/survey-plan/PlanEditorPage'));
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
    { path: '/survey', title: 'survey.page.overview', component: Hub },
    { path: '/survey/points', title: 'survey.page.register', component: Page },
    { path: '/survey/plan', title: 'plan.page.title', component: PlanPage },
    { path: '/survey/calc', title: 'survey.cogo.title', component: CalcPage },
  ],
  // An old /survey link still lands on a page that says how to switch survey on.
  // Any /survey sub-page (a bookmark, another browser) says the same instead of 404.
  offRoutes: [
    { path: '/survey', title: 'survey.page.overview', component: Setup },
    { path: '/survey/*', title: 'survey.page.overview', component: Setup },
  ],
  navItems: [
    { labelKey: 'survey.page.overview', to: '/survey', icon: Compass, group: 'grp_survey' },
    { labelKey: 'survey.page.register', to: '/survey/points', icon: Crosshair, group: 'grp_survey' },
    { labelKey: 'plan.page.title', to: '/survey/plan', icon: PenTool, group: 'grp_survey' },
    { labelKey: 'survey.cogo.title', to: '/survey/calc', icon: Calculator, group: 'grp_survey' },
  ],
};
