// Design module (ERP side of the design editor link).
import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/** ?project=<id> (links in notifications and tasks) switches the ERP to that project once. */
export function useProjectFromUrl(): void {
  const [params] = useSearchParams();
  const wanted = params.get('project');
  const active = useProjectContextStore((s) => s.activeProjectId);
  const setActive = useProjectContextStore((s) => s.setActiveProject);
  const applied = useRef<string | null>(null);
  useEffect(() => {
    if (!wanted || applied.current === wanted) return;
    applied.current = wanted; // once per link: switching project afterwards is the person's choice
    if (wanted !== active) setActive(wanted, '');
  }, [wanted, active, setActive]);
}
