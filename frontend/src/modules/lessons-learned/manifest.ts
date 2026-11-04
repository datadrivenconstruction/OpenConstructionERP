// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { lazy } from 'react';
import { BookOpen } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const Page = lazy(() => import('@/features/lessons-learned/LessonsLearnedPage'));

export const manifest: ModuleManifest = {
  id: 'lessons-learned',
  name: 'lessons_learned.title',
  description: 'lessons_learned.module_description',
  version: '1.0.0',
  icon: BookOpen,
  category: 'tools',
  defaultEnabled: true,
  depends: [],
  routes: [{ path: '/lessons-learned', title: 'lessons_learned.title', component: Page }],
  // No sidebar row: the register opens from the "seen on N past projects" badge and the risk register.
  navItems: [],
  translations: {
    en: {
      'lessons_learned.title': 'Lessons learned',
      'lessons_learned.module_description':
        'Lessons captured at project closeout, tagged by trade, cost code and risk, shown on estimates and risks.',
    },
    de: {
      'lessons_learned.title': 'Lessons Learned',
      'lessons_learned.module_description':
        'Beim Projektabschluss erfasste Erkenntnisse mit Gewerk, Kostenkennzahl und Risiko, sichtbar in Kalkulation und Risiken.',
    },
    ru: {
      'lessons_learned.title': 'Извлечённые уроки',
      'lessons_learned.module_description':
        'Уроки, записанные при закрытии проекта: вид работ, код затрат и риск. Показываются в сметах и рисках.',
    },
  },
};
