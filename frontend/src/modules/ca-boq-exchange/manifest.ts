import { lazy } from 'react';
import { MapPin } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const CAExchangeModule = lazy(() => import('./CAExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'ca-boq-exchange',
  name: 'Canada BOQ Exchange',
  description: 'Import/export BOQs in Canadian MasterFormat/CIQS format (Excel/CSV)',
  version: '1.0.0',
  icon: MapPin,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/ca-boq-exchange',
      title: 'Canada BOQ Exchange',
      component: CAExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.ca_boq_exchange',
      to: '/ca-boq-exchange',
      icon: MapPin,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Canada BOQ Import / Export',
      path: '/ca-boq-exchange',
      keywords: [
        'canada',
        'canadian',
        'ciqs',
        'masterformat',
        'merx',
        'altus',
        'csc',
        'quantity surveyor',
      ],
    },
  ],
  translations: {
    en: {
      'nav.ca_boq_exchange': 'Canada BOQ Exchange',
      'ca.title': 'Canada BOQ Import / Export',
      'ca.subtitle': 'Exchange Bills of Quantities in Canadian MasterFormat / CIQS format (Excel / CSV)',
      'ca.tab_import': 'Import',
      'ca.tab_export': 'Export',
      'ca.import_complete': 'Canadian BOQ import complete',
      'ca.export_complete': 'Canadian BOQ export complete',
      'ca.info': 'Canadian construction uses CSI MasterFormat (adapted for Canada by CSC) and CIQS (Canadian Institute of Quantity Surveyors) standards. Compatible with MERX, Altus Group, and provincial tendering systems.',
      'ca.drop_file': 'Drop a Canadian BOQ file here (Excel or CSV), or',
      'ca.browse': 'Browse files',
      'ca.formats_hint': 'Supported: .csv, .tsv, .xlsx (MasterFormat/CIQS-formatted BOQ)',
      'ca.classification': 'MasterFormat/CIQS Code',
      'ca.export_format': 'Format',
      'ca.csv_format': 'CSV (Excel-compatible)',
      'ca.detailed': 'MasterFormat Detailed',
      'ca.summary': 'CIQS Summary',
    },
    fr: {
      'nav.ca_boq_exchange': 'Bordereau canadien',
      'ca.title': 'Bordereau canadien Import / Export',
      'ca.subtitle': 'Echange de bordereaux de quantites au format canadien MasterFormat / CIQS (Excel / CSV)',
      'ca.tab_import': 'Importer',
      'ca.tab_export': 'Exporter',
      'ca.import_complete': 'Importation du bordereau canadien terminee',
      'ca.export_complete': 'Exportation du bordereau canadien terminee',
      'ca.info': 'La construction canadienne utilise le CSI MasterFormat (adapte pour le Canada par CSC) et les normes CIQS (Institut canadien des metreurs). Compatible avec MERX, Altus Group et les systemes d\'appel d\'offres provinciaux.',
      'ca.drop_file': 'Deposez un fichier de bordereau canadien ici (Excel ou CSV), ou',
      'ca.browse': 'Parcourir les fichiers',
      'ca.formats_hint': 'Formats acceptes : .csv, .tsv, .xlsx (bordereau format MasterFormat/CIQS)',
      'ca.classification': 'Code MasterFormat/CIQS',
      'ca.export_format': 'Format',
      'ca.detailed': 'MasterFormat detaille',
      'ca.summary': 'Resume CIQS',
    },
    de: {
      'nav.ca_boq_exchange': 'Kanada LV Austausch',
      'ca.title': 'Kanada LV Import / Export',
      'ca.subtitle': 'Leistungsverzeichnis im kanadischen MasterFormat/CIQS-Format austauschen (Excel / CSV)',
      'ca.tab_import': 'Importieren',
      'ca.tab_export': 'Exportieren',
      'ca.import_complete': 'Kanadischer LV-Import abgeschlossen',
      'ca.export_complete': 'Kanadischer LV-Export abgeschlossen',
    },
    ru: {
      'nav.ca_boq_exchange': 'Kanada BOQ Obmen',
      'ca.title': 'Kanada BOQ Import / Eksport',
      'ca.subtitle': 'Obmen dannymi smety v kanadskom formate MasterFormat / CIQS (Excel / CSV)',
      'ca.tab_import': 'Import',
      'ca.tab_export': 'Eksport',
    },
  },
};
