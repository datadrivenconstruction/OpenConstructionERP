import { ShieldCheck } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'validation',
  name: 'validation.title',
  description: 'modules.validation_desc',
  version: '1.0.0',
  icon: ShieldCheck,
  category: 'tools',
  defaultEnabled: true,
  routes: [],
  navItems: [],
};
