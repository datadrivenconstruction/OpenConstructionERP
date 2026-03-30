import { lazy } from 'react';
import { Building2 } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const TRExchangeModule = lazy(() => import('./TRExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'tr-birimfiyat-exchange',
  name: 'Turkey Birim Fiyat Exchange',
  description: 'Import/export BOQs in Turkish Bayindirlik Birim Fiyat format (Excel/CSV)',
  version: '1.0.0',
  icon: Building2,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/tr-birimfiyat-exchange',
      title: 'Turkey Birim Fiyat Exchange',
      component: TRExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.tr_birimfiyat_exchange',
      to: '/tr-birimfiyat-exchange',
      icon: Building2,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Turkey Birim Fiyat Import / Export',
      path: '/tr-birimfiyat-exchange',
      keywords: [
        'turkey',
        'turkish',
        'türkiye',
        'birim fiyat',
        'bayındırlık',
        'pozları',
        'keşif',
        'metraj',
        'lira',
        'try',
      ],
    },
  ],
  translations: {
    en: {
      'nav.tr_birimfiyat_exchange': 'Turkey Birim Fiyat Exchange',
      'tr.title': 'Turkey Birim Fiyat Import / Export',
      'tr.subtitle':
        'Exchange Bills of Quantities in Bayindirlik Birim Fiyat format (Excel / CSV)',
      'tr.tab_import': 'Import',
      'tr.tab_export': 'Export',
      'tr.import_complete': 'Turkish Birim Fiyat import complete',
      'tr.export_complete': 'Turkish Birim Fiyat export complete',
      'tr.info':
        'Bayindirlik Birim Fiyat is the official unit price system published by the Turkish Ministry of Environment, Urbanisation and Climate Change. It defines standardised work items (poz) and unit prices for public construction projects across Turkey.',
      'tr.drop_file': 'Drop a Turkish Birim Fiyat BOQ file here (Excel or CSV), or',
      'tr.browse': 'Browse files',
      'tr.formats_hint': 'Supported: .csv, .tsv, .xlsx (Birim Fiyat-formatted BOQ)',
      'tr.classification': 'Birim Fiyat Poz',
      'tr.export_format': 'Format',
      'tr.csv_format': 'CSV (Excel-compatible)',
      'tr.detailed': 'Birim Fiyat Detailed',
      'tr.summary': 'Birim Fiyat Summary',
    },
    tr: {
      'nav.tr_birimfiyat_exchange': 'Birim Fiyat Veri Aktarimi',
      'tr.title': 'Birim Fiyat Iceri/Disari Aktarma',
      'tr.subtitle':
        'Bayindirlik Birim Fiyat formatinda kesif ozeti alip verme (Excel / CSV)',
      'tr.tab_import': 'Iceri Aktar',
      'tr.tab_export': 'Disari Aktar',
      'tr.import_complete': 'Birim Fiyat iceri aktarma tamamlandi',
      'tr.export_complete': 'Birim Fiyat disari aktarma tamamlandi',
      'tr.info':
        'Bayindirlik Birim Fiyat, Cevre, Sehircilik ve Iklim Degisikligi Bakanligi tarafindan yayimlanan resmi birim fiyat sistemidir. Turkiye genelinde kamu insaat projelerinde standart is kalemleri (poz) ve birim fiyatlari tanimlar.',
      'tr.drop_file': 'Birim Fiyat dosyasini buraya surukleyin (Excel veya CSV), veya',
      'tr.browse': 'Dosya sec',
      'tr.formats_hint': 'Desteklenen: .csv, .tsv, .xlsx (Birim Fiyat formatli kesif)',
      'tr.classification': 'Birim Fiyat Poz No',
      'tr.export_format': 'Format',
      'tr.csv_format': 'CSV (Excel uyumlu)',
      'tr.detailed': 'Birim Fiyat Detayli',
      'tr.summary': 'Birim Fiyat Ozet',
    },
    de: {
      'nav.tr_birimfiyat_exchange': 'Türkei Birim Fiyat Austausch',
      'tr.title': 'Türkei Birim Fiyat Import / Export',
      'tr.subtitle':
        'Leistungsverzeichnis im Bayindirlik Birim Fiyat-Format austauschen (Excel / CSV)',
      'tr.tab_import': 'Importieren',
      'tr.tab_export': 'Exportieren',
      'tr.import_complete': 'Türkisches Birim Fiyat-Import abgeschlossen',
      'tr.export_complete': 'Türkisches Birim Fiyat-Export abgeschlossen',
    },
    ru: {
      'nav.tr_birimfiyat_exchange': 'Turcija Birim Fiyat Obmen',
      'tr.title': 'Turcija Birim Fiyat Import / Export',
      'tr.subtitle': 'Obmen dannymi smety v formate Bayindirlik Birim Fiyat (Excel / CSV)',
      'tr.tab_import': 'Import',
      'tr.tab_export': 'Eksport',
    },
  },
};
