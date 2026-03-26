import { lazy } from 'react';
import { Map } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const AUExchangeModule = lazy(() => import('./AUExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'au-boq-exchange',
  name: 'Australia BOQ Exchange',
  description: 'Import/export BOQs in Australian ACMM/ANZSMM format (Excel/CSV)',
  version: '1.0.0',
  icon: Map,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/au-boq-exchange',
      title: 'Australia BOQ Exchange',
      component: AUExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.au_boq_exchange',
      to: '/au-boq-exchange',
      icon: Map,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Australia BOQ Import / Export',
      path: '/au-boq-exchange',
      keywords: [
        'australia',
        'australian',
        'acmm',
        'anzsmm',
        'rawlinsons',
        'aiqs',
        'quantity surveyor',
        'boq',
      ],
    },
  ],
  translations: {
    en: {
      'nav.au_boq_exchange': 'Australia BOQ Exchange',
      'au.title': 'Australia BOQ Import / Export',
      'au.subtitle': 'Exchange Bills of Quantities in ACMM/ANZSMM format (Excel / CSV)',
      'au.tab_import': 'Import',
      'au.tab_export': 'Export',
      'au.import_complete': 'Australian BOQ import complete',
      'au.export_complete': 'Australian BOQ export complete',
      'au.info': 'ACMM (Australian Cost Management Manual) and ANZSMM (Australian & New Zealand Standard Method of Measurement) are the primary standards used by Australian quantity surveyors. Compatible with AIQS guidelines, Rawlinsons cost data, and Australian QS practices.',
      'au.drop_file': 'Drop an Australian BOQ file here (Excel or CSV), or',
      'au.browse': 'Browse files',
      'au.formats_hint': 'Supported: .csv, .tsv, .xlsx (ACMM/ANZSMM-formatted BOQ)',
      'au.classification': 'ACMM Trade',
      'au.export_format': 'Format',
      'au.csv_format': 'CSV (Excel-compatible)',
      'au.detailed': 'ACMM Detailed',
      'au.summary': 'ACMM Summary',
    },
    de: {
      'nav.au_boq_exchange': 'Australien LV Austausch',
      'au.title': 'Australien LV Import / Export',
      'au.subtitle': 'Leistungsverzeichnis im ACMM/ANZSMM-Format austauschen (Excel / CSV)',
      'au.tab_import': 'Importieren',
      'au.tab_export': 'Exportieren',
      'au.import_complete': 'Australisches LV-Import abgeschlossen',
      'au.export_complete': 'Australisches LV-Export abgeschlossen',
    },
    ru: {
      'nav.au_boq_exchange': 'Avstralija BOQ Obmen',
      'au.title': 'Avstralija BOQ Import / Export',
      'au.subtitle': 'Obmen dannymi smety v formate ACMM/ANZSMM (Excel / CSV)',
      'au.tab_import': 'Import',
      'au.tab_export': 'Eksport',
    },
  },
};
