// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** The open demo's project scope for list pages (see `demoScope.ts`). */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from './api';
import { demoScopeFor, type DemoProjectRef, type DemoScopeState } from './demoScope';
import { fetchProjectList } from './projectList';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

export interface DemoScope extends DemoScopeState {
  demoMode: boolean;
  showAll: boolean;
  setShowAll: (showAll: boolean) => void;
}

export function useDemoScope(): DemoScope {
  const { data: sys } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<{ demo_mode?: boolean }>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });
  const demoMode = sys?.demo_mode === true;
  const slug = useDemoSessionStore((s) => s.slug);
  const showAll = useDemoSessionStore((s) => s.showAll);
  const setShowAll = useDemoSessionStore((s) => s.setShowAll);
  // Same key and reader as the demo switcher, so this shares its cache.
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<DemoProjectRef[]>(),
    staleTime: 60_000,
    enabled: demoMode && !!slug,
  });
  return { ...demoScopeFor({ demoMode, slug, showAll, projects }), demoMode, showAll, setShowAll };
}
