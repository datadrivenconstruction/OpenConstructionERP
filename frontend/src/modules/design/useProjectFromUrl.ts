// Design module (ERP side of the design editor link).
import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiGet } from '@/shared/lib/api';
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
    if (wanted === active) return;
    setActive(wanted, '');
    // the header shows the name; without it the picker reads "Select project" while the page shows the project
    apiGet<{ name?: string }>(`/v1/projects/${wanted}`)
      .then((p) => {
        if (p?.name && useProjectContextStore.getState().activeProjectId === wanted) setActive(wanted, p.name);
      })
      .catch(() => undefined);
  }, [wanted, active, setActive]);
}
