// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { MailSearch } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const CommsIntelligenceModule = lazy(
  () => import('./CommsIntelligenceModule'),
) as unknown as LazyExoticComponent<ComponentType<unknown>>;

export const manifest: ModuleManifest = {
  id: 'comms-intelligence',
  name: 'modules.comms_intelligence.name',
  description: 'modules.comms_intelligence.description',
  version: '0.1.0',
  icon: MailSearch,
  category: 'tools',
  defaultEnabled: true,
  routes: [
    {
      path: '/comms-intelligence',
      title: 'nav.comms_intelligence',
      component: CommsIntelligenceModule,
    },
  ],
  navItems: [
    {
      // Still being built out, so it lives under the WIP group at the
      // bottom of the sidebar rather than up in Overview. No special row
      // colouring — it reads like every other nav row.
      labelKey: 'nav.comms_intelligence',
      to: '/comms-intelligence',
      icon: MailSearch,
      group: 'grp_communication',
      advancedOnly: false,
    },
  ],
  translations: {
    en: {
      'modules.comms_intelligence.name': 'Comms Intelligence',
      'modules.comms_intelligence.description':
        'Classifies inbound correspondence, extracts prices and deadlines, drafts replies, and tracks who owes whom a response',
      'nav.comms_intelligence': 'Comms Intelligence',
    },
    de: {
      'modules.comms_intelligence.name': 'Komm-Intelligenz',
      'modules.comms_intelligence.description':
        'Klassifiziert eingehende Korrespondenz, extrahiert Preise und Fristen, entwirft Antworten und verfolgt offene Rückmeldungen',
      'nav.comms_intelligence': 'Komm-Intelligenz',
    },
    fr: {
      'modules.comms_intelligence.name': 'Analyse de la correspondance',
      'modules.comms_intelligence.description':
        'Classe la correspondance entrante, en extrait les prix et les échéances, rédige des réponses et suit qui doit une réponse à qui',
      'nav.comms_intelligence': 'Analyse de la correspondance',
    },
    ru: {
      'modules.comms_intelligence.name': 'Аналитика переписки',
      'modules.comms_intelligence.description':
        'Классифицирует входящую корреспонденцию, извлекает цены и сроки, готовит черновики ответов и отслеживает, кто кому должен ответ',
      'nav.comms_intelligence': 'Аналитика переписки',
    },
  },
};
