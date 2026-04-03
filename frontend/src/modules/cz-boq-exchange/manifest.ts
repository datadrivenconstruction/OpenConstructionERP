import { lazy } from 'react';
import { Landmark } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const CZExchangeModule = lazy(() => import('./CZExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'cz-boq-exchange',
  name: 'Czech URS Exchange',
  description: 'Import/export BOQs in Czech URS / TSKP format (Excel/CSV)',
  version: '1.0.0',
  icon: Landmark,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/cz-boq-exchange',
      title: 'Czech URS Exchange',
      component: CZExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.cz_boq_exchange',
      to: '/cz-boq-exchange',
      icon: Landmark,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Czech URS / TSKP Import / Export',
      path: '/cz-boq-exchange',
      keywords: [
        'czech',
        'cestina',
        'cesko',
        'slovakia',
        'slovensko',
        'urs',
        'tskp',
        'cenova soustava',
        'rozpocet',
        'kc',
        'czk',
      ],
    },
  ],
  translations: {
    en: {
      'nav.cz_boq_exchange': 'Czech URS Exchange',
      'cz.title': 'Czech BOQ Import / Export',
      'cz.subtitle': 'Exchange Bills of Quantities in Czech URS / TSKP format (Excel / CSV)',
      'cz.tab_import': 'Import',
      'cz.tab_export': 'Export',
      'cz.import_complete': 'Czech BOQ import complete',
      'cz.export_complete': 'Czech BOQ export complete',
      'cz.info':
        'Czech construction uses URS (Ucelovy registr stavebnich praci) and TSKP (Tridnik stavebnich konstrukci a praci) classification systems. Compatible with KROS, euroCALC, BUILDpower, and RTS stavitel+.',
      'cz.drop_file': 'Drop a Czech BOQ file here (Excel or CSV), or',
      'cz.browse': 'Browse files',
      'cz.formats_hint': 'Supported: .csv, .tsv, .xlsx (URS/TSKP-formatted BOQ)',
      'cz.classification': 'URS / TSKP Code',
      'cz.export_format': 'Format',
      'cz.csv_format': 'CSV (Excel-compatible)',
      'cz.detailed': 'URS Detailed',
      'cz.summary': 'URS Summary',
    },
    cs: {
      'nav.cz_boq_exchange': 'Cesky URS vymena',
      'cz.title': 'Cesky rozpocet Import / Export',
      'cz.subtitle': 'Vymena rozpoctu ve formatu URS / TSKP (Excel / CSV)',
      'cz.tab_import': 'Import',
      'cz.tab_export': 'Export',
      'cz.import_complete': 'Import ceskeho rozpoctu dokoncen',
      'cz.export_complete': 'Export ceskeho rozpoctu dokoncen',
      'cz.info':
        'Ceske stavebnictvi pouziva klasifikacni systemy URS (Ucelovy registr stavebnich praci) a TSKP (Tridnik stavebnich konstrukci a praci). Kompatibilni s KROS, euroCALC, BUILDpower a RTS stavitel+.',
      'cz.drop_file': 'Pretahnete sem cesky soubor rozpoctu (Excel nebo CSV), nebo',
      'cz.browse': 'Vybrat soubory',
      'cz.formats_hint': 'Podporovane: .csv, .tsv, .xlsx (rozpocet ve formatu URS/TSKP)',
      'cz.classification': 'Kod URS / TSKP',
      'cz.export_format': 'Format',
      'cz.csv_format': 'CSV (kompatibilni s Excelem)',
      'cz.detailed': 'URS podrobny',
      'cz.summary': 'URS souhrnny',
    },
    de: {
      'nav.cz_boq_exchange': 'Tschechischer LV Austausch',
      'cz.title': 'Tschechischer LV Import / Export',
      'cz.subtitle':
        'Leistungsverzeichnis im tschechischen URS / TSKP-Format austauschen (Excel / CSV)',
      'cz.tab_import': 'Importieren',
      'cz.tab_export': 'Exportieren',
      'cz.import_complete': 'Tschechischer LV-Import abgeschlossen',
      'cz.export_complete': 'Tschechischer LV-Export abgeschlossen',
    },
    ru: {
      'nav.cz_boq_exchange': 'Cheshskij BOQ Obmen',
      'cz.title': 'Cheshskij BOQ Import / Eksport',
      'cz.subtitle': 'Obmen dannymi smety v cheshskom formate URS / TSKP (Excel / CSV)',
      'cz.tab_import': 'Import',
      'cz.tab_export': 'Eksport',
    },
  },
};
