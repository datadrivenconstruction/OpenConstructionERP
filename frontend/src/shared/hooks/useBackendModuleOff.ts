// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Whether a backend module is switched off on the System Modules tab.
 *
 * Reads the catalogue the sidebar and the Modules page share, under the same
 * `['system-modules']` key and the same un-caught `apiGet` (a cached empty
 * list would reach the Modules page as a real answer), so one request serves
 * every caller and a toggle there updates them all.
 *
 * Fail-open: while the list loads, when it fails, and for a module it does not
 * name, the answer is "not off". Only a non-core module the catalogue reports
 * as disabled is off; core modules cannot be switched off.
 */

import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

interface BackendModuleState {
  name: string;
  enabled: boolean;
  is_core: boolean;
}

export function useBackendModuleOff(): (name: string) => boolean {
  const { data } = useQuery({
    queryKey: ['system-modules'],
    queryFn: () => apiGet<BackendModuleState[]>('/v1/modules/'),
    staleTime: 30 * 1000,
    gcTime: 5 * 60 * 1000,
  });
  return useCallback(
    (name: string) => (data ?? []).some((m) => m.name === name && !m.is_core && !m.enabled),
    [data],
  );
}
