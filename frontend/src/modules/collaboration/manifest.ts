import { lazy } from 'react';
import { Users } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'collaboration',
  name: 'Real-time Collaboration',
  description: 'Collaborate on estimates with your team in real-time using Yjs CRDT',
  version: '1.0.0',
  icon: Users,
  category: 'tools',
  defaultEnabled: true,
  depends: ['boq'],
  routes: [
    {
      path: '/collaboration',
      title: 'Collaboration',
      component: lazy(() => import('./CollaborationModule')),
    },
  ],
  navItems: [
    {
      labelKey: 'nav.collaboration',
      to: '/collaboration',
      icon: Users,
      group: 'tools',
      advancedOnly: true,
    },
  ],
  searchEntries: [
    {
      label: 'Real-time Collaboration',
      path: '/collaboration',
      keywords: ['collaboration', 'realtime', 'yjs', 'multiplayer', 'share', 'team', 'crdt'],
    },
  ],
  translations: {
    en: {
      'collab.peers_connected': '{{count}} peer(s) connected',
      'collab.share_link': 'Share collaboration link',
      'collab.conflict_detected': 'Conflict detected',
      'collab.keep_mine': 'Keep mine',
      'collab.accept_theirs': 'Accept theirs',
      'collab.resolve_manually': 'Resolve manually',
      'collab.no_conflicts': 'No conflicts',
    },
    de: {
      'collab.peers_connected': '{{count}} Teilnehmer verbunden',
      'collab.share_link': 'Kollaborations-Link teilen',
      'collab.conflict_detected': 'Konflikt erkannt',
      'collab.keep_mine': 'Meine behalten',
      'collab.accept_theirs': 'Ihre übernehmen',
      'collab.resolve_manually': 'Manuell lösen',
      'collab.no_conflicts': 'Keine Konflikte',
    },
    fr: {
      'collab.peers_connected': '{{count}} participant(s) connecté(s)',
      'collab.share_link': 'Partager le lien de collaboration',
      'collab.conflict_detected': 'Conflit détecté',
      'collab.keep_mine': 'Garder le mien',
      'collab.accept_theirs': 'Accepter le leur',
      'collab.resolve_manually': 'Résoudre manuellement',
      'collab.no_conflicts': 'Aucun conflit',
    },
    ru: {
      'collab.peers_connected': '{{count}} участник(ов) подключено',
      'collab.share_link': 'Поделиться ссылкой',
      'collab.conflict_detected': 'Обнаружен конфликт',
      'collab.keep_mine': 'Оставить мои',
      'collab.accept_theirs': 'Принять их',
      'collab.resolve_manually': 'Решить вручную',
      'collab.no_conflicts': 'Конфликтов нет',
    },
  },
};
