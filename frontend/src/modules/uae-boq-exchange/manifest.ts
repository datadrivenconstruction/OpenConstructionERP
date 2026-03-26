import { lazy } from 'react';
import { Building2 } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const UAEExchangeModule = lazy(() => import('./UAEExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'uae-boq-exchange',
  name: 'UAE BOQ Exchange',
  description: 'Import/export BOQs in UAE FIDIC-based format (NRM/POMI standard, Excel/CSV)',
  version: '1.0.0',
  icon: Building2,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/uae-boq-exchange',
      title: 'UAE BOQ Exchange',
      component: UAEExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.uae_boq_exchange',
      to: '/uae-boq-exchange',
      icon: Building2,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'UAE BOQ Import / Export',
      path: '/uae-boq-exchange',
      keywords: [
        'uae',
        'dubai',
        'abu dhabi',
        'fidic',
        'pomi',
        'nrm',
        'gulf',
        'gcc',
        'middle east',
        'emirates',
      ],
    },
  ],
  translations: {
    en: {
      'nav.uae_boq_exchange': 'UAE BOQ Exchange',
      'uae.title': 'UAE BOQ Import / Export',
      'uae.subtitle': 'Exchange Bills of Quantities in UAE FIDIC / NRM-POMI format (Excel / CSV)',
      'uae.tab_import': 'Import',
      'uae.tab_export': 'Export',
      'uae.import_complete': 'UAE BOQ import complete',
      'uae.export_complete': 'UAE BOQ export complete',
      'uae.info': 'UAE construction projects typically follow FIDIC contract forms with BOQs structured per NRM/POMI hybrid standards. This module supports the GCC market format used across Dubai, Abu Dhabi, and other Emirates, with AED currency and common trade sections for high-rise, infrastructure, and MEP-heavy projects.',
      'uae.drop_file': 'Drop a UAE BOQ file here (Excel or CSV), or',
      'uae.browse': 'Browse files',
      'uae.formats_hint': 'Supported: .csv, .tsv, .xlsx (FIDIC/NRM-formatted BOQ)',
      'uae.classification': 'Trade Section',
      'uae.export_format': 'Format',
      'uae.csv_format': 'CSV (Excel-compatible)',
      'uae.fidic_detailed': 'FIDIC Detailed',
      'uae.fidic_summary': 'Summary',
    },
    ar: {
      'nav.uae_boq_exchange': '\u062A\u0628\u0627\u062F\u0644 \u062C\u062F\u0627\u0648\u0644 \u0627\u0644\u0643\u0645\u064A\u0627\u062A \u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062A',
      'uae.title': '\u0627\u0633\u062A\u064A\u0631\u0627\u062F / \u062A\u0635\u062F\u064A\u0631 \u062C\u062F\u0627\u0648\u0644 \u0627\u0644\u0643\u0645\u064A\u0627\u062A',
      'uae.subtitle': '\u062A\u0628\u0627\u062F\u0644 \u062C\u062F\u0627\u0648\u0644 \u0627\u0644\u0643\u0645\u064A\u0627\u062A \u0628\u0635\u064A\u063A\u0629 FIDIC / NRM-POMI',
      'uae.tab_import': '\u0627\u0633\u062A\u064A\u0631\u0627\u062F',
      'uae.tab_export': '\u062A\u0635\u062F\u064A\u0631',
      'uae.import_complete': '\u0627\u0643\u062A\u0645\u0644 \u0627\u0633\u062A\u064A\u0631\u0627\u062F \u062C\u062F\u0648\u0644 \u0627\u0644\u0643\u0645\u064A\u0627\u062A',
      'uae.export_complete': '\u0627\u0643\u062A\u0645\u0644 \u062A\u0635\u062F\u064A\u0631 \u062C\u062F\u0648\u0644 \u0627\u0644\u0643\u0645\u064A\u0627\u062A',
    },
    de: {
      'nav.uae_boq_exchange': 'UAE LV-Austausch',
      'uae.title': 'UAE LV Import / Export',
      'uae.subtitle': 'Leistungsverzeichnis im UAE FIDIC/NRM-POMI-Format austauschen (Excel / CSV)',
      'uae.tab_import': 'Importieren',
      'uae.tab_export': 'Exportieren',
      'uae.import_complete': 'UAE LV-Import abgeschlossen',
      'uae.export_complete': 'UAE LV-Export abgeschlossen',
    },
    ru: {
      'nav.uae_boq_exchange': 'OAE Obmen BOQ',
      'uae.title': 'OAE Smeta Import / Export',
      'uae.subtitle': 'Obmen dannymi smety v formate FIDIC / NRM-POMI (Excel / CSV)',
      'uae.tab_import': 'Import',
      'uae.tab_export': 'Eksport',
      'uae.import_complete': 'Import smety OAE zavershyon',
      'uae.export_complete': 'Eksport smety OAE zavershyon',
    },
  },
};
