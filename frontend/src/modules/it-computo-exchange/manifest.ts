import { lazy } from 'react';
import { Euro } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const ITExchangeModule = lazy(() => import('./ITExchangeModule'));

export const manifest: ModuleManifest = {
  id: 'it-computo-exchange',
  name: 'Italy Computo Metrico Exchange',
  description:
    'Import/export BOQs in Italian Computo Metrico / Prezzario DEI format (Excel/CSV)',
  version: '1.0.0',
  icon: Euro,
  category: 'regional',
  defaultEnabled: false,
  depends: ['boq'],
  routes: [
    {
      path: '/it-computo-exchange',
      title: 'Italy Computo Metrico Exchange',
      component: ITExchangeModule,
    },
  ],
  navItems: [
    {
      labelKey: 'nav.it_computo_exchange',
      to: '/it-computo-exchange',
      icon: Euro,
      group: 'regional',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Italy Computo Metrico Import / Export',
      path: '/it-computo-exchange',
      keywords: [
        'italy',
        'italian',
        'italia',
        'computo metrico',
        'prezzario',
        'dei',
        'estimativo',
        'capitolo',
        'voce',
        'lavorazione',
        'eur',
      ],
    },
  ],
  translations: {
    en: {
      'nav.it_computo_exchange': 'Italy Computo Metrico Exchange',
      'it_cm.title': 'Italy Computo Metrico Import / Export',
      'it_cm.subtitle':
        'Exchange Bills of Quantities in Computo Metrico / Prezzario DEI format (Excel / CSV)',
      'it_cm.tab_import': 'Import',
      'it_cm.tab_export': 'Export',
      'it_cm.import_complete': 'Italian Computo Metrico import complete',
      'it_cm.export_complete': 'Italian Computo Metrico export complete',
      'it_cm.info':
        'Computo Metrico Estimativo is the standard Italian construction cost estimation document. Combined with Prezzario DEI (published by DEI - Tipografia del Genio Civile), it provides official regional unit prices used for public and private construction projects across Italy.',
      'it_cm.drop_file': 'Drop an Italian Computo Metrico file here (Excel or CSV), or',
      'it_cm.browse': 'Browse files',
      'it_cm.formats_hint':
        'Supported: .csv, .tsv, .xlsx (Computo Metrico / Prezzario DEI-formatted BOQ)',
      'it_cm.classification': 'Capitolo',
      'it_cm.export_format': 'Format',
      'it_cm.csv_format': 'CSV (Excel-compatible)',
      'it_cm.detailed': 'Computo Detailed',
      'it_cm.summary': 'Computo Summary',
    },
    it: {
      'nav.it_computo_exchange': 'Computo Metrico Scambio Dati',
      'it_cm.title': 'Computo Metrico Importa / Esporta',
      'it_cm.subtitle':
        'Scambio computi metrici in formato Computo Metrico / Prezzario DEI (Excel / CSV)',
      'it_cm.tab_import': 'Importa',
      'it_cm.tab_export': 'Esporta',
      'it_cm.import_complete': 'Importazione Computo Metrico completata',
      'it_cm.export_complete': 'Esportazione Computo Metrico completata',
      'it_cm.info':
        'Il Computo Metrico Estimativo e il documento standard italiano per la stima dei costi di costruzione. Insieme al Prezzario DEI (pubblicato da DEI - Tipografia del Genio Civile), fornisce i prezzi unitari ufficiali regionali utilizzati per i progetti di costruzione pubblici e privati in tutta Italia.',
      'it_cm.drop_file': 'Trascina qui un file Computo Metrico (Excel o CSV), oppure',
      'it_cm.browse': 'Sfoglia file',
      'it_cm.formats_hint':
        'Supportati: .csv, .tsv, .xlsx (Computo Metrico / Prezzario DEI)',
      'it_cm.classification': 'Capitolo',
      'it_cm.export_format': 'Formato',
      'it_cm.csv_format': 'CSV (compatibile Excel)',
      'it_cm.detailed': 'Computo Dettagliato',
      'it_cm.summary': 'Computo Riepilogativo',
    },
    de: {
      'nav.it_computo_exchange': 'Italien Computo Metrico Austausch',
      'it_cm.title': 'Italien Computo Metrico Import / Export',
      'it_cm.subtitle':
        'Leistungsverzeichnis im Computo Metrico / Prezzario DEI-Format austauschen (Excel / CSV)',
      'it_cm.tab_import': 'Importieren',
      'it_cm.tab_export': 'Exportieren',
      'it_cm.import_complete': 'Italienisches Computo Metrico-Import abgeschlossen',
      'it_cm.export_complete': 'Italienisches Computo Metrico-Export abgeschlossen',
    },
    ru: {
      'nav.it_computo_exchange': 'Italija Computo Metrico Obmen',
      'it_cm.title': 'Italija Computo Metrico Import / Export',
      'it_cm.subtitle':
        'Obmen dannymi smety v formate Computo Metrico / Prezzario DEI (Excel / CSV)',
      'it_cm.tab_import': 'Import',
      'it_cm.tab_export': 'Eksport',
    },
  },
};
