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
  // navItems intentionally empty. The /benchmarks row already lives in the
  // sidebar as a static entry in the grp_cost_data group (Sidebar.tsx), gated
  // by moduleKey 'cost-benchmark' and advancedOnly. The sidebar only pulls
  // dynamic module navItems for its static group ids (grp_*, regional), never
  // for the legacy 'tools' group string a manifest would declare here, so an
  // entry would either render nowhere or duplicate the existing nav source.
  navItems: [],
  searchEntries: [
    {
      label: 'Cost Benchmarks',
      path: '/benchmarks',
      keywords: ['benchmark', 'bki', 'bcis', 'cost per m2', 'percentile', 'comparison'],
    },
  ],
};
