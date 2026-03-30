import { lazy } from 'react';
import { Building } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const JPExchangeModule = lazy(() => import('./JPExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'jp-sekisan-exchange',
  name: 'Japan Sekisan Exchange',
  description:
    'Import/export BOQs in Japanese \u7A4D\u7B97\u57FA\u6E96 (Sekisan Kijun) format (Excel/CSV)',
  version: '1.0.0',
  icon: Building,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/jp-sekisan-exchange',
      title: 'Japan Sekisan Exchange',
      component: JPExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.jp_sekisan_exchange',
      to: '/jp-sekisan-exchange',
      icon: Building,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Japan Sekisan Import / Export',
      path: '/jp-sekisan-exchange',
      keywords: [
        'japan',
        'japanese',
        '\u65E5\u672C',
        '\u7A4D\u7B97',
        'sekisan',
        'kijun',
        '\u898B\u7A4D',
        '\u6570\u91CF\u8ABF\u66F8',
        'mitsumori',
        'jbci',
        'yen',
        'jpy',
      ],
    },
  ],
  translations: {
    en: {
      'nav.jp_sekisan_exchange': 'Japan Sekisan Exchange',
      'jp.title': 'Japan Sekisan Import / Export',
      'jp.subtitle':
        'Exchange Bills of Quantities in \u7A4D\u7B97\u57FA\u6E96 (Sekisan Kijun) format (Excel / CSV)',
      'jp.tab_import': 'Import',
      'jp.tab_export': 'Export',
      'jp.import_complete': 'Japanese Sekisan import complete',
      'jp.export_complete': 'Japanese Sekisan export complete',
      'jp.info':
        '\u7A4D\u7B97\u57FA\u6E96 (Sekisan Kijun) is the official Japanese construction cost estimation standard maintained by the Ministry of Land, Infrastructure, Transport and Tourism (MLIT). It is widely used for public works cost estimation, compatible with JBCI cost data and Japanese QS practices.',
      'jp.drop_file': 'Drop a Japanese Sekisan BOQ file here (Excel or CSV), or',
      'jp.browse': 'Browse files',
      'jp.formats_hint': 'Supported: .csv, .tsv, .xlsx (Sekisan Kijun-formatted BOQ)',
      'jp.classification': 'Sekisan Code',
      'jp.export_format': 'Format',
      'jp.csv_format': 'CSV (Excel-compatible)',
      'jp.detailed': 'Sekisan Detailed',
      'jp.summary': 'Sekisan Summary',
    },
    ja: {
      'nav.jp_sekisan_exchange': '\u7A4D\u7B97\u57FA\u6E96 \u30C7\u30FC\u30BF\u4EA4\u63DB',
      'jp.title': '\u7A4D\u7B97\u57FA\u6E96 \u30A4\u30F3\u30DD\u30FC\u30C8 / \u30A8\u30AF\u30B9\u30DD\u30FC\u30C8',
      'jp.subtitle':
        '\u7A4D\u7B97\u57FA\u6E96\u5F62\u5F0F\u3067\u6570\u91CF\u8ABF\u66F8\u3092\u4EA4\u63DB (Excel / CSV)',
      'jp.tab_import': '\u30A4\u30F3\u30DD\u30FC\u30C8',
      'jp.tab_export': '\u30A8\u30AF\u30B9\u30DD\u30FC\u30C8',
      'jp.import_complete': '\u7A4D\u7B97\u57FA\u6E96\u30A4\u30F3\u30DD\u30FC\u30C8\u5B8C\u4E86',
      'jp.export_complete': '\u7A4D\u7B97\u57FA\u6E96\u30A8\u30AF\u30B9\u30DD\u30FC\u30C8\u5B8C\u4E86',
      'jp.info':
        '\u7A4D\u7B97\u57FA\u6E96\u306F\u3001\u56FD\u571F\u4EA4\u901A\u7701\u304C\u7BA1\u7406\u3059\u308B\u65E5\u672C\u306E\u516C\u5F0F\u5EFA\u8A2D\u30B3\u30B9\u30C8\u898B\u7A4D\u57FA\u6E96\u3067\u3059\u3002\u516C\u5171\u4E8B\u696D\u306E\u30B3\u30B9\u30C8\u898B\u7A4D\u306B\u5E83\u304F\u4F7F\u7528\u3055\u308C\u3001JBCI\u30B3\u30B9\u30C8\u30C7\u30FC\u30BF\u304A\u3088\u3073\u65E5\u672C\u306E\u7A4D\u7B97\u5B9F\u52D9\u3068\u4E92\u63DB\u6027\u304C\u3042\u308A\u307E\u3059\u3002',
      'jp.drop_file': '\u7A4D\u7B97\u57FA\u6E96BOQ\u30D5\u30A1\u30A4\u30EB\u3092\u3053\u3053\u306B\u30C9\u30ED\u30C3\u30D7 (Excel\u307E\u305F\u306FCSV)\u3001\u307E\u305F\u306F',
      'jp.browse': '\u30D5\u30A1\u30A4\u30EB\u3092\u9078\u629E',
      'jp.formats_hint': '\u5BFE\u5FDC: .csv, .tsv, .xlsx (\u7A4D\u7B97\u57FA\u6E96\u5F62\u5F0F\u306EBOQ)',
      'jp.classification': '\u7A4D\u7B97\u30B3\u30FC\u30C9',
      'jp.export_format': '\u30D5\u30A9\u30FC\u30DE\u30C3\u30C8',
      'jp.csv_format': 'CSV (Excel\u4E92\u63DB)',
      'jp.detailed': '\u7A4D\u7B97 \u8A73\u7D30',
      'jp.summary': '\u7A4D\u7B97 \u6982\u8981',
    },
    de: {
      'nav.jp_sekisan_exchange': 'Japan Sekisan Austausch',
      'jp.title': 'Japan Sekisan Import / Export',
      'jp.subtitle':
        'Leistungsverzeichnis im \u7A4D\u7B97\u57FA\u6E96 (Sekisan Kijun)-Format austauschen (Excel / CSV)',
      'jp.tab_import': 'Importieren',
      'jp.tab_export': 'Exportieren',
      'jp.import_complete': 'Japanisches Sekisan-Import abgeschlossen',
      'jp.export_complete': 'Japanisches Sekisan-Export abgeschlossen',
    },
    ru: {
      'nav.jp_sekisan_exchange': 'Japonija Sekisan Obmen',
      'jp.title': 'Japonija Sekisan Import / Export',
      'jp.subtitle': 'Obmen dannymi smety v formate Sekisan Kijun (Excel / CSV)',
      'jp.tab_import': 'Import',
      'jp.tab_export': 'Eksport',
    },
  },
};
