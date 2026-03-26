import { FileText } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'tendering',
  name: 'tendering.title',
  description: 'modules.tendering_desc',
  version: '1.0.0',
  icon: FileText,
  category: 'procurement',
  defaultEnabled: true,
  routes: [],
  navItems: [],
};
