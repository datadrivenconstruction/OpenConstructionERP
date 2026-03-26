import { Layers } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'assemblies',
  name: 'nav.assemblies',
  description: 'modules.assemblies_desc',
  version: '1.0.0',
  icon: Layers,
  category: 'estimation',
  defaultEnabled: true,
  routes: [],
  navItems: [],
};
