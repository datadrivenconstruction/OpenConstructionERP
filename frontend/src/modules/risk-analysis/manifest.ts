import { lazy } from 'react';
import { Dices } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const RiskAnalysisModule = lazy(() => import('./RiskAnalysisModule'));

export const manifest: ModuleManifest = {
  id: 'risk-analysis',
  name: 'Risk Analysis (Monte Carlo)',
  description: 'Probabilistic cost estimation with Monte Carlo simulation, sensitivity analysis, and contingency recommendations',
  version: '1.0.0',
  icon: Dices,
  category: 'tools',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/risk-analysis',
      title: 'Risk Analysis',
      component: RiskAnalysisModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.risk_analysis',
      to: '/risk-analysis',
      icon: Dices,
      group: 'tools',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Risk Analysis / Monte Carlo',
      path: '/risk-analysis',
      keywords: ['monte carlo', 'risk', 'probability', 'contingency', 'simulation', 'p80', 'percentile', 'uncertainty'],
    },
  ],
  translations: {
    en: {
      'nav.risk_analysis': 'Risk Analysis',
      'risk.title': 'Risk Analysis (Monte Carlo)',
      'risk.subtitle': 'Probabilistic cost estimation with Monte Carlo simulation',
      'risk.run': 'Run Monte Carlo Simulation',
      'risk.running': 'Running simulation...',
      'risk.contingency': 'Contingency (P80 − P50)',
      'risk.recommended_budget': 'Recommended Budget (P80)',
      'risk.top_drivers': 'Top 10 Risk Drivers',
      'risk.distribution': 'Cost Distribution (Histogram)',
    },
    de: {
      'nav.risk_analysis': 'Risikoanalyse',
      'risk.title': 'Risikoanalyse (Monte Carlo)',
      'risk.subtitle': 'Probabilistische Kostenermittlung mit Monte-Carlo-Simulation',
      'risk.run': 'Monte-Carlo-Simulation starten',
      'risk.running': 'Simulation läuft...',
      'risk.contingency': 'Risikovorsorge (P80 − P50)',
      'risk.recommended_budget': 'Empfohlenes Budget (P80)',
      'risk.top_drivers': 'Top 10 Risikotreiber',
      'risk.distribution': 'Kostenverteilung (Histogramm)',
    },
    fr: {
      'nav.risk_analysis': 'Analyse des risques',
      'risk.title': 'Analyse des risques (Monte Carlo)',
      'risk.subtitle': 'Estimation probabiliste des coûts par simulation Monte Carlo',
      'risk.run': 'Lancer la simulation Monte Carlo',
      'risk.running': 'Simulation en cours...',
      'risk.contingency': 'Provision (P80 − P50)',
      'risk.recommended_budget': 'Budget recommandé (P80)',
    },
    ru: {
      'nav.risk_analysis': 'Анализ рисков',
      'risk.title': 'Анализ рисков (Монте-Карло)',
      'risk.subtitle': 'Вероятностная оценка стоимости методом Монте-Карло',
      'risk.run': 'Запустить симуляцию Монте-Карло',
      'risk.running': 'Симуляция выполняется...',
      'risk.contingency': 'Резерв (P80 − P50)',
      'risk.recommended_budget': 'Рекомендуемый бюджет (P80)',
      'risk.top_drivers': 'Топ-10 факторов риска',
      'risk.distribution': 'Распределение стоимости (гистограмма)',
    },
  },
};
