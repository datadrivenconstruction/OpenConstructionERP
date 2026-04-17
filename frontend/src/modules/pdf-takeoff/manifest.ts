import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import { Ruler } from 'lucide-react';
import type { ModuleManifest } from '../_types';

// The module accepts optional props (for in-app embedding); cast to the
// module-route's `ComponentType<unknown>` signature so the manifest type
// remains uniform across all modules.
const TakeoffViewerModule = lazy(
  () => import('./TakeoffViewerModule'),
) as unknown as LazyExoticComponent<ComponentType<unknown>>;

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
      component: TakeoffViewerModule,
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
