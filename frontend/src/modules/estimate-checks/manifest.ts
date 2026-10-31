// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { Gauge } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const SettingsPage = lazy(() => import('@/features/estimate-checks/EstimateChecksSettingsPage'));

export const manifest: ModuleManifest = {
  id: 'estimate-checks',
  name: 'estimate_checks.title',
  description: 'estimate_checks.module_description',
  version: '1.0.0',
  icon: Gauge,
  category: 'estimation',
  defaultEnabled: true,
  depends: ['boq'],
  routes: [
    {
      path: '/estimate-checks',
      title: 'estimate_checks.settings.title',
      component: SettingsPage,
    },
  ],
  // No sidebar row: the check lives in the estimate header; settings open from its panel.
  navItems: [],
  translations: {
    en: {
      'estimate_checks.title': 'Estimate check',
      'estimate_checks.module_description':
        'Traffic-light sanity check of an estimate against your past estimates before you submit it.',
      'estimate_checks.settings.title': 'Estimate check settings',
    },
    de: {
      'estimate_checks.title': 'Kalkulationsprüfung',
      'estimate_checks.module_description':
        'Ampelprüfung einer Kalkulation gegen Ihre früheren Kalkulationen, bevor Sie sie abgeben.',
      'estimate_checks.settings.title': 'Einstellungen der Kalkulationsprüfung',
    },
    ru: {
      'estimate_checks.title': 'Проверка сметы',
      'estimate_checks.module_description':
        'Проверка сметы по принципу светофора: сравнение с прошлыми сметами компании перед подачей.',
      'estimate_checks.settings.title': 'Настройки проверки сметы',
    },
  },
};
