import { lazy } from 'react';
import { Ruler } from 'lucide-react';
import type { ModuleManifest } from '../_types';

export const manifest: ModuleManifest = {
  id: 'pdf-takeoff',
  name: 'PDF Takeoff Viewer',
  description: 'View PDFs and take measurements directly on drawings',
  version: '1.0.0',
  icon: Ruler,
  category: 'tools',
  defaultEnabled: true,
  routes: [
    {
      path: '/takeoff-viewer',
      title: 'PDF Takeoff',
      component: lazy(() => import('./TakeoffViewerModule')),
    },
  ],
  navItems: [],
  searchEntries: [
    {
      label: 'Measurements',
      path: '/takeoff-viewer',
      keywords: ['pdf', 'takeoff', 'measure', 'measurements', 'drawing', 'distance', 'area', 'count', 'ruler'],
    },
  ],
};
