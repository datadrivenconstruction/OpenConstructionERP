import { lazy } from 'react';
import { PoundSterling } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const NRMExchangeModule = lazy(() => import('./NRMExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'uk-nrm-exchange',
  name: 'UK NRM BOQ Exchange',
  description: 'Import and export Bills of Quantities in UK NRM 1/2 format (Excel/CSV)',
  version: '1.0.0',
  icon: PoundSterling,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/uk-nrm-exchange',
      title: 'UK NRM Exchange',
      component: NRMExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.uk_nrm_exchange',
      to: '/uk-nrm-exchange',
      icon: PoundSterling,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'UK NRM BOQ Import / Export',
      path: '/uk-nrm-exchange',
      keywords: ['uk', 'nrm', 'bcis', 'rics', 'british', 'england', 'boq', 'excel', 'measurement'],
    },
  ],
  translations: {
    en: {
      'nav.uk_nrm_exchange': 'UK NRM Exchange',
      'nrm.title': 'UK NRM BOQ Import / Export',
      'nrm.subtitle': 'Exchange Bills of Quantities in NRM 1/2 format (Excel / CSV)',
      'nrm.tab_import': 'Import',
      'nrm.tab_export': 'Export',
      'nrm.import_complete': 'NRM BOQ import complete',
      'nrm.export_complete': 'NRM BOQ export complete',
      'nrm.info': 'NRM (New Rules of Measurement) is the UK standard published by RICS. NRM 1 covers cost planning, NRM 2 covers detailed measurement. Compatible with BCIS, RICS guidelines, and UK QS practices.',
      'nrm.drop_file': 'Drop an NRM BOQ file here (Excel or CSV), or',
      'nrm.browse': 'Browse files',
      'nrm.formats_hint': 'Supported: .csv, .tsv, .xlsx (NRM-formatted BOQ)',
      'nrm.classification': 'NRM Element',
      'nrm.export_format': 'Format',
      'nrm.csv_format': 'CSV (Excel-compatible)',
      'nrm.detailed': 'NRM 2 Detailed',
      'nrm.summary': 'NRM 1 Summary',
    },
    de: {
      'nav.uk_nrm_exchange': 'UK NRM Austausch',
      'nrm.title': 'UK NRM LV Import / Export',
      'nrm.subtitle': 'Leistungsverzeichnis im NRM 1/2-Format austauschen (Excel / CSV)',
      'nrm.tab_import': 'Importieren',
      'nrm.tab_export': 'Exportieren',
      'nrm.import_complete': 'NRM LV-Import abgeschlossen',
      'nrm.export_complete': 'NRM LV-Export abgeschlossen',
    },
    fr: {
      'nav.uk_nrm_exchange': 'Echange NRM UK',
      'nrm.title': 'UK NRM DQE Import / Export',
      'nrm.tab_import': 'Importer',
      'nrm.tab_export': 'Exporter',
    },
    ru: {
      'nav.uk_nrm_exchange': 'UK NRM Obmen',
      'nrm.title': 'UK NRM Smeta Import / Export',
      'nrm.subtitle': 'Obmen dannymi smety v formate NRM 1/2 (Excel / CSV)',
      'nrm.tab_import': 'Import',
      'nrm.tab_export': 'Eksport',
    },
  },
};
