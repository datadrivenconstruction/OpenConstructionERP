import { lazy } from 'react';
import { BarChart3 } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const BenchmarkModule = lazy(() => import('./BenchmarkModule'));

export const manifest: ModuleManifest = {
  id: 'cost-benchmark',
  name: 'modules.cost_benchmark.name',
  description: 'modules.cost_benchmark.description',
  version: '1.0.0',
  icon: BarChart3,
  category: 'tools',
  defaultEnabled: true,
  depends: ['costs'],
  routes: [
    {
      path: '/benchmarks',
      title: 'Cost Benchmarks',
      component: BenchmarkModule,
    },
  ],
  navItems: [],
  searchEntries: [
    {
      label: 'Cost Benchmarks',
      path: '/benchmarks',
      keywords: ['benchmark', 'bki', 'bcis', 'cost per m2', 'percentile', 'comparison'],
    },
  ],
};
