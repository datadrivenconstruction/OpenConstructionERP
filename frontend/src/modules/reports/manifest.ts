import { FileBarChart } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'reports',
  name: 'nav.reports',
  description: 'modules.reports_desc',
  version: '1.0.0',
  icon: FileBarChart,
  category: 'procurement',
  defaultEnabled: true,
  routes: [],
  navItems: [],
};
