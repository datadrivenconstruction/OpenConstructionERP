import { lazy } from 'react';
import { FileText } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const GAEBExchangeModule = lazy(() => import('./GAEBExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'gaeb-exchange',
  name: 'GAEB XML 3.3 Import / Export',
  description: 'Exchange BOQ data in GAEB DA XML 3.3 format — import X81/X83 files and export tender/bid documents',
  version: '1.0.0',
  icon: FileText,
  category: 'tools',
  defaultEnabled: true,
  depends: ['boq'],
  routes: [
    {
      path: '/gaeb-exchange',
      title: 'GAEB Exchange',
      component: GAEBExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.gaeb_exchange',
      to: '/gaeb-exchange',
      icon: FileText,
      group: 'tools',
    },
  ],
  searchEntries: [
    {
      label: 'GAEB XML Import / Export',
      path: '/gaeb-exchange',
      keywords: ['gaeb', 'xml', 'x81', 'x83', 'tender', 'bid', 'lv', 'leistungsverzeichnis', 'ava', 'din', 'dach'],
    },
  ],
  translations: {
    en: {
      'nav.gaeb_exchange': 'GAEB Exchange',
      'gaeb.title': 'GAEB XML 3.3 Import / Export',
      'gaeb.subtitle': 'Exchange BOQ data in GAEB DA XML format (X81 / X83)',
      'gaeb.tab_import': 'Import',
      'gaeb.tab_export': 'Export',
      'gaeb.import_complete': 'GAEB import complete',
      'gaeb.export_complete': 'GAEB export complete',
    },
    de: {
      'nav.gaeb_exchange': 'GAEB-Austausch',
      'gaeb.title': 'GAEB DA XML 3.3 Import / Export',
      'gaeb.subtitle': 'Leistungsverzeichnis im GAEB DA XML-Format austauschen (X81 / X83)',
      'gaeb.tab_import': 'Importieren',
      'gaeb.tab_export': 'Exportieren',
      'gaeb.import_complete': 'GAEB-Import abgeschlossen',
      'gaeb.export_complete': 'GAEB-Export abgeschlossen',
      'gaeb.x83_desc': 'Angebotsabgabe (mit Preisen)',
      'gaeb.x81_desc': 'Leistungsverzeichnis (ohne Preise)',
      'gaeb.drop_file': 'GAEB XML-Datei hierher ziehen, oder',
      'gaeb.browse': 'Datei auswählen',
    },
    fr: {
      'nav.gaeb_exchange': 'Échange GAEB',
      'gaeb.title': 'GAEB DA XML 3.3 Import / Export',
      'gaeb.subtitle': 'Échanger les données de DQE au format GAEB DA XML (X81 / X83)',
      'gaeb.tab_import': 'Importer',
      'gaeb.tab_export': 'Exporter',
      'gaeb.import_complete': 'Import GAEB terminé',
      'gaeb.export_complete': 'Export GAEB terminé',
    },
    ru: {
      'nav.gaeb_exchange': 'GAEB Обмен',
      'gaeb.title': 'GAEB DA XML 3.3 Импорт / Экспорт',
      'gaeb.subtitle': 'Обмен данными сметы в формате GAEB DA XML (X81 / X83)',
      'gaeb.tab_import': 'Импорт',
      'gaeb.tab_export': 'Экспорт',
      'gaeb.import_complete': 'Импорт GAEB завершён',
      'gaeb.export_complete': 'Экспорт GAEB завершён',
      'gaeb.x83_desc': 'Предложение (с ценами)',
      'gaeb.x81_desc': 'Спецификация (без цен)',
    },
  },
};
