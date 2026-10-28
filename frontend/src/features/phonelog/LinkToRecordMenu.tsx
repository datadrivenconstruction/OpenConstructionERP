// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Link to record" - the affordance that turns a logged call into connected
// evidence. From a call it deep-links to the project's RFIs or change orders,
// where the user raises or opens the formal record the call substantiates.
//
// This is a navigation-only link. Persisting a hard reference (call <-> RFI /
// change-order id) so the two rows point at each other needs a backend field
// and endpoint that do not exist yet, so that is intentionally left out; see
// the page report for the flag.

import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ChevronDown, FileEdit, HelpCircle, Link2 } from 'lucide-react';

export function LinkToRecordMenu({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const go = (path: string) => {
    setOpen(false);
    navigate(path);
  };

  // RFIs have a project-scoped route; change orders use the active project.
  const rfiPath = projectId ? `/projects/${projectId}/rfi` : '/rfi';

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
      >
        <Link2 className="h-3.5 w-3.5" />
        {t('phonelog.link_record', { defaultValue: 'Link to record' })}
        <ChevronDown className="h-3.5 w-3.5" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute z-20 mt-1 w-64 rounded-lg border border-border-light bg-surface-elevated p-1 shadow-lg"
        >
          <p className="px-2 py-1.5 text-2xs leading-relaxed text-content-tertiary">
            {t('phonelog.link_hint', {
              defaultValue: 'Open the record this call substantiates and raise or update it there.',
            })}
          </p>
          <button
            type="button"
            role="menuitem"
            onClick={() => go(rfiPath)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-content-primary hover:bg-surface-secondary"
          >
            <HelpCircle className="h-4 w-4 shrink-0 text-content-tertiary" />
            {t('phonelog.link_open_rfi', { defaultValue: 'Open RFIs' })}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => go('/changeorders')}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-content-primary hover:bg-surface-secondary"
          >
            <FileEdit className="h-4 w-4 shrink-0 text-content-tertiary" />
            {t('phonelog.link_open_co', { defaultValue: 'Open change orders' })}
          </button>
        </div>
      )}
    </div>
  );
}
