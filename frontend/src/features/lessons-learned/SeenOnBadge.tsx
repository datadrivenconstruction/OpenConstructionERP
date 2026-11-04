// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BookOpen } from 'lucide-react';
import { useModuleStore } from '@/stores/useModuleStore';
import { lessonsApi, type SeenQuery } from './api';

export const MODULE_KEY = 'lessons-learned';

/**
 * "Seen on N past projects": how many other projects hold a confirmed lesson for the same trade,
 * cost code or risk category. Renders nothing while the module is off, the lookup fails or nothing matches.
 */
export function SeenOnBadge(props: SeenQuery) {
  const { t } = useTranslation();
  const enabled = useModuleStore((s) => s.isModuleEnabled(MODULE_KEY));
  const [open, setOpen] = useState(false);
  const { projectId, trade, costCode, riskCategory } = props;
  const { data } = useQuery({
    queryKey: ['lessons-learned', 'seen', projectId, trade, costCode, riskCategory],
    queryFn: () => lessonsApi.seen({ projectId, trade, costCode, riskCategory }),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
  if (!enabled || !data || data.projects === 0) return null;

  return (
    <div className="relative inline-block">
      <button
        type="button"
        data-testid="seen-on-badge"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-light px-2.5 text-xs font-medium
                   text-content-secondary hover:bg-surface-secondary"
      >
        <BookOpen size={14} />
        {t('lessons_learned.seen', { count: data.projects, defaultValue: 'Seen on {{count}} past projects' })}
      </button>
      {open && (
        <div
          data-testid="seen-on-popover"
          className="absolute end-0 z-20 mt-1 w-80 rounded-lg border border-border-light bg-surface-primary p-3 shadow-lg"
        >
          <ul className="space-y-2">
            {data.top.map((l) => (
              <li key={l.id} className="text-xs">
                <div className="font-medium text-content-primary">{l.title}</div>
                {l.recommendation && <div className="text-content-secondary">{l.recommendation}</div>}
              </li>
            ))}
          </ul>
          <Link to="/lessons-learned" className="mt-2 block text-xs font-medium text-oe-blue hover:underline">
            {t('lessons_learned.open_register', { defaultValue: 'Open the lessons register' })}
          </Link>
        </div>
      )}
    </div>
  );
}
