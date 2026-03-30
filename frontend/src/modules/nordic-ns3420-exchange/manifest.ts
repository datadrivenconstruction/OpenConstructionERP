import { lazy } from 'react';
import { Snowflake } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const NordicExchangeModule = lazy(() => import('./NordicExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'nordic-ns3420-exchange',
  name: 'Nordic Standards Exchange',
  description: 'Import/export BOQs in Nordic NS 3420 / AMA / V&S format (Excel/CSV)',
  version: '1.0.0',
  icon: Snowflake,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/nordic-ns3420-exchange',
      title: 'Nordic Standards Exchange',
      component: NordicExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.nordic_ns3420_exchange',
      to: '/nordic-ns3420-exchange',
      icon: Snowflake,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Nordic NS 3420 / AMA / V&S Import / Export',
      path: '/nordic-ns3420-exchange',
      keywords: [
        'nordic',
        'scandinavia',
        'norway',
        'norsk',
        'sweden',
        'swedish',
        'svenska',
        'denmark',
        'danish',
        'dansk',
        'finland',
        'finnish',
        'suomi',
        'ns3420',
        'ama',
        'v&s',
        'bygge',
      ],
    },
  ],
  translations: {
    en: {
      'nav.nordic_ns3420_exchange': 'Nordic Standards Exchange',
      'nordic.title': 'Nordic BOQ Import / Export',
      'nordic.subtitle':
        'Exchange Bills of Quantities in Nordic NS 3420 / AMA / V&S format (Excel / CSV)',
      'nordic.tab_import': 'Import',
      'nordic.tab_export': 'Export',
      'nordic.import_complete': 'Nordic BOQ import complete',
      'nordic.export_complete': 'Nordic BOQ export complete',
      'nordic.info':
        'Nordic construction uses NS 3420 (Norway), AMA (Sweden), V&S (Denmark), and Talo (Finland) classification systems. This module supports import/export compatible with Holte, ISY, BidCon, and Sigma Estimates.',
      'nordic.drop_file': 'Drop a Nordic BOQ file here (Excel or CSV), or',
      'nordic.browse': 'Browse files',
      'nordic.formats_hint': 'Supported: .csv, .tsv, .xlsx (NS 3420/AMA/V&S-formatted BOQ)',
      'nordic.classification': 'NS 3420 Code',
      'nordic.export_format': 'Format',
      'nordic.csv_format': 'CSV (Excel-compatible)',
      'nordic.detailed': 'NS 3420 Detailed',
      'nordic.summary': 'NS 3420 Summary',
    },
    no: {
      'nav.nordic_ns3420_exchange': 'Nordisk standardutveksling',
      'nordic.title': 'Nordisk mengdebeskrivelse Import / Eksport',
      'nordic.subtitle':
        'Utveksle mengdebeskrivelser i nordisk NS 3420 / AMA / V&S-format (Excel / CSV)',
      'nordic.tab_import': 'Importer',
      'nordic.tab_export': 'Eksporter',
      'nordic.import_complete': 'Nordisk mengdebeskrivelse-import fullfort',
      'nordic.export_complete': 'Nordisk mengdebeskrivelse-eksport fullfort',
      'nordic.info':
        'Nordisk bygg bruker NS 3420 (Norge), AMA (Sverige), V&S (Danmark) og Talo (Finland) klassifiseringssystemer. Denne modulen stotter import/eksport kompatibel med Holte, ISY, BidCon og Sigma Estimates.',
      'nordic.drop_file': 'Slipp en nordisk mengdebeskrivelse-fil her (Excel eller CSV), eller',
      'nordic.browse': 'Bla gjennom filer',
      'nordic.formats_hint':
        'Stottet: .csv, .tsv, .xlsx (NS 3420/AMA/V&S-formatert mengdebeskrivelse)',
      'nordic.classification': 'NS 3420-kode',
      'nordic.export_format': 'Format',
      'nordic.csv_format': 'CSV (Excel-kompatibel)',
      'nordic.detailed': 'NS 3420 Detaljert',
      'nordic.summary': 'NS 3420 Sammendrag',
    },
    sv: {
      'nav.nordic_ns3420_exchange': 'Nordisk standardutbyte',
      'nordic.title': 'Nordisk mangdforteckning Import / Export',
      'nordic.tab_import': 'Importera',
      'nordic.tab_export': 'Exportera',
      'nordic.import_complete': 'Nordisk mangdforteckning-import klar',
      'nordic.export_complete': 'Nordisk mangdforteckning-export klar',
    },
    da: {
      'nav.nordic_ns3420_exchange': 'Nordisk standardudveksling',
      'nordic.title': 'Nordisk tilbudsliste Import / Eksport',
      'nordic.tab_import': 'Importer',
      'nordic.tab_export': 'Eksporter',
      'nordic.import_complete': 'Nordisk tilbudsliste-import fuldfort',
      'nordic.export_complete': 'Nordisk tilbudsliste-eksport fuldfort',
    },
    fi: {
      'nav.nordic_ns3420_exchange': 'Pohjoismainen standardinvaihto',
      'nordic.title': 'Pohjoismainen maaraluettelo tuonti / vienti',
      'nordic.tab_import': 'Tuo',
      'nordic.tab_export': 'Vie',
      'nordic.import_complete': 'Pohjoismainen maaraluettelo-tuonti valmis',
      'nordic.export_complete': 'Pohjoismainen maaraluettelo-vienti valmis',
    },
    de: {
      'nav.nordic_ns3420_exchange': 'Nordischer LV Austausch',
      'nordic.title': 'Nordischer LV Import / Export',
      'nordic.subtitle':
        'Leistungsverzeichnis im nordischen NS 3420 / AMA / V&S-Format austauschen (Excel / CSV)',
      'nordic.tab_import': 'Importieren',
      'nordic.tab_export': 'Exportieren',
      'nordic.import_complete': 'Nordischer LV-Import abgeschlossen',
      'nordic.export_complete': 'Nordischer LV-Export abgeschlossen',
    },
    ru: {
      'nav.nordic_ns3420_exchange': 'Nordicheskij BOQ Obmen',
      'nordic.title': 'Nordicheskij BOQ Import / Eksport',
      'nordic.subtitle':
        'Obmen dannymi smety v nordicheskom formate NS 3420 / AMA / V&S (Excel / CSV)',
      'nordic.tab_import': 'Import',
      'nordic.tab_export': 'Eksport',
    },
  },
};
