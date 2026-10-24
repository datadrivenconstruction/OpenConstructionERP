// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useQuery } from '@tanstack/react-query';
import { fetchProjectList } from '@/shared/lib/projectList';
import { projectColor } from '@/shared/lib/projectColor';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/**
 * Colour of the active project, or null outside a project. Reads the shared
 * ['projects'] list the header switcher already keeps warm, so no extra request.
 */
export function useActiveProjectColor(): string | null {
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Array<{ id: string; name: string; color?: string | null }>>(),
    staleTime: 60_000,
  });
  if (!activeProjectId) return null;
  const hit = data?.find((p) => p.id === activeProjectId);
  return projectColor(hit ?? { id: activeProjectId });
}
