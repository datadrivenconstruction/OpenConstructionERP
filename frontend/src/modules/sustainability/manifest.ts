import { lazy } from 'react';
import { Leaf } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const SustainabilityPage = lazy(() =>
  import('@/features/sustainability/SustainabilityPage').then((m) => ({
    default: m.SustainabilityPage,
  })),
);

export const manifest: ModuleManifest = {
  id: 'sustainability',
  name: 'modules.sustainability.name',
  description: 'modules.sustainability.description',
  version: '1.0.0',
  icon: Leaf,
  category: 'tools',
  defaultEnabled: true,
  depends: ['boq'],
  routes: [
    {
      path: '/sustainability',
      title: 'Sustainability',
      component: SustainabilityPage,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.sustainability',
      to: '/sustainability',
      icon: Leaf,
      group: 'tools',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Sustainability / EPD',
      path: '/sustainability',
      keywords: ['carbon', 'co2', 'epd', 'gwp', 'embodied', 'green', 'environment'],
    },
  ],
  translations: {
    en: {
      'sustainability.epd_data': 'EPD Data',
      'sustainability.carbon_budget': 'Carbon Budget',
      'sustainability.lifecycle_phase': 'Life Cycle Phase',
    },
    de: {
      'sustainability.epd_data': 'EPD-Daten',
      'sustainability.carbon_budget': 'CO₂-Budget',
      'sustainability.lifecycle_phase': 'Lebenszyklusphase',
    },
    fr: {
      'sustainability.epd_data': 'Données EPD',
      'sustainability.carbon_budget': 'Budget carbone',
      'sustainability.lifecycle_phase': 'Phase du cycle de vie',
    },
    ru: {
      'sustainability.epd_data': 'Данные EPD',
      'sustainability.carbon_budget': 'Углеродный бюджет',
      'sustainability.lifecycle_phase': 'Фаза жизненного цикла',
    },
  },
};
