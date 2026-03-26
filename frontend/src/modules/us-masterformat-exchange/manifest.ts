import { lazy } from 'react';
import { DollarSign } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const MasterFormatExchangeModule = lazy(() => import('./MasterFormatExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'us-masterformat-exchange',
  name: 'US MasterFormat BOQ Exchange',
  description:
    'Import and export Bills of Quantities in CSI MasterFormat / UniFormat (Excel/CSV)',
  version: '1.0.0',
  icon: DollarSign,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/us-masterformat-exchange',
      title: 'US MasterFormat Exchange',
      component: MasterFormatExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.us_masterformat_exchange',
      to: '/us-masterformat-exchange',
      icon: DollarSign,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'US MasterFormat BOQ Import / Export',
      path: '/us-masterformat-exchange',
      keywords: [
        'us',
        'usa',
        'masterformat',
        'uniformat',
        'csi',
        'american',
        'rsmeans',
        'aia',
        'division',
      ],
    },
  ],
  translations: {
    en: {
      'nav.us_masterformat_exchange': 'US MasterFormat Exchange',
      'mf.title': 'US MasterFormat BOQ Import / Export',
      'mf.subtitle': 'Exchange BOQ data in CSI MasterFormat / UniFormat (Excel / CSV)',
      'mf.tab_import': 'Import',
      'mf.tab_export': 'Export',
      'mf.import_complete': 'MasterFormat BOQ import complete',
      'mf.export_complete': 'MasterFormat BOQ export complete',
      'mf.info':
        'MasterFormat is the CSI/CSC standard for organizing construction specifications in North America. It uses a 6-digit numbering system organized into 50 divisions (00-49). Compatible with RSMeans, AIA documents, and major US estimating software.',
      'mf.drop_file': 'Drop a MasterFormat BOQ file here (Excel or CSV), or',
      'mf.browse': 'Browse files',
      'mf.formats_hint': 'Supported: .csv, .tsv, .xlsx (MasterFormat/UniFormat BOQ)',
      'mf.classification': 'Division',
      'mf.masterformat': 'MasterFormat',
      'mf.uniformat': 'UniFormat',
    },
    de: {
      'nav.us_masterformat_exchange': 'US MasterFormat Austausch',
      'mf.title': 'US MasterFormat LV Import / Export',
      'mf.subtitle':
        'Leistungsverzeichnis im CSI MasterFormat / UniFormat austauschen (Excel / CSV)',
      'mf.tab_import': 'Importieren',
      'mf.tab_export': 'Exportieren',
      'mf.import_complete': 'MasterFormat LV-Import abgeschlossen',
      'mf.export_complete': 'MasterFormat LV-Export abgeschlossen',
    },
    ru: {
      'nav.us_masterformat_exchange': 'US MasterFormat Обмен',
      'mf.title': 'US MasterFormat Смета Импорт / Экспорт',
      'mf.subtitle': 'Обмен данными сметы в формате CSI MasterFormat / UniFormat (Excel / CSV)',
      'mf.tab_import': 'Импорт',
      'mf.tab_export': 'Экспорт',
      'mf.import_complete': 'Импорт MasterFormat сметы завершён',
      'mf.export_complete': 'Экспорт MasterFormat сметы завершён',
    },
  },
};
