import { CalendarDays } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'schedule',
  name: 'schedule.title',
  description: 'modules.schedule_desc',
  version: '1.0.0',
  icon: CalendarDays,
  category: 'planning',
  defaultEnabled: true,
  routes: [],
  navItems: [],
};
