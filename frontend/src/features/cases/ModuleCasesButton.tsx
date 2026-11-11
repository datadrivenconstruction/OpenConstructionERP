// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ModuleCasesButton — a small pill that sits next to the module's "How it
// works" guide button and answers "which guided cases (playbooks) use THIS
// module?". It reads the current route, looks the module's cases up in the
// playbook<->route index, and on click/hover drops a menu of those cases,
// each linking to the in-app case runner (/cases/:id) so the user can open
// one and follow it step by step.
//
// It is entirely route-derived and self-hiding: on a page whose route no
// playbook touches it renders nothing, so it can live inside the shared
// ModuleGuideButton and appear on every module that actually has cases,
// with zero per-page wiring.

import { useCallback, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { BookOpen, ArrowRight } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { playbooksForRoute } from './playbookModules';

const MAX_SHOWN = 6;

export interface ModuleCasesButtonProps {
  /** Optional extra classes for layout-specific tweaks. */
  className?: string;
}

export function ModuleCasesButton({ className }: ModuleCasesButtonProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<number | null>(null);

  const cases = playbooksForRoute(location.pathname);

  const clearClose = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  const openNow = useCallback(() => {
    clearClose();
    setOpen(true);
  }, [clearClose]);

  // Small grace period so moving the pointer from the button into the menu
  // does not flicker it shut.
  const scheduleClose = useCallback(() => {
    clearClose();
    closeTimer.current = window.setTimeout(() => setOpen(false), 160);
  }, [clearClose]);

  // Nothing touches this route — render nothing so headers stay clean.
  if (cases.length === 0) return null;

  const shown = cases.slice(0, MAX_SHOWN);
  const label = t('cases_for_module.button', { defaultValue: 'Cases' });
  const aria = t('cases_for_module.button_aria', {
    defaultValue: 'Guided cases that use this module',
  });

  const goToCase = (id: string) => {
    setOpen(false);
    navigate(`/cases/${id}`);
  };

  return (
    <div
      className={clsx('relative', className)}
      onMouseEnter={openNow}
      onMouseLeave={scheduleClose}
    >
      <Button
        variant="secondary"
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setOpen(false);
        }}
        data-testid="module-cases-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={aria}
        title={aria}
        icon={<BookOpen size={16} strokeWidth={2} className="text-semantic-success" />}
      >
        <span className="hidden sm:inline">{label}</span>
        <span className="ms-1.5 inline-flex items-center justify-center rounded-full bg-surface-tertiary text-content-secondary text-2xs font-semibold min-w-[16px] h-4 px-1 leading-none">
          {cases.length}
        </span>
      </Button>

      {open && (
        <div
          role="menu"
          aria-label={aria}
          className={clsx(
            'absolute right-0 top-[calc(100%+6px)] z-dropdown w-72 max-w-[86vw]',
            'rounded-xl border border-border-light bg-surface-primary shadow-xl p-2',
            'animate-card-in',
          )}
          onMouseEnter={openNow}
          onMouseLeave={scheduleClose}
        >
          <p className="oe-overline px-2 pt-1 pb-1.5">
            {t('cases_for_module.heading', {
              defaultValue: 'Playbooks that use this module',
            })}
          </p>
          <ul className="flex flex-col">
            {shown.map((pb) => (
              <li key={pb.id}>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => goToCase(pb.id)}
                  className="group w-full text-left flex items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-secondary transition-colors"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-medium text-content-primary leading-snug">
                      {t(pb.titleKey, { defaultValue: pb.titleDefault })}
                    </span>
                    <span className="block text-2xs text-content-tertiary mt-0.5">
                      {t('cases_for_module.steps_count', {
                        count: pb.steps.length,
                        defaultValue_one: '{{count}} step',
                        defaultValue: '{{count}} steps',
                      })}
                    </span>
                  </span>
                  <ArrowRight
                    size={14}
                    className="shrink-0 mt-0.5 text-content-quaternary group-hover:text-semantic-success transition-colors"
                    aria-hidden
                  />
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              navigate('/cases');
            }}
            className="mt-1 w-full flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-2xs font-semibold text-semantic-success hover:bg-semantic-success/10 transition-colors"
          >
            {cases.length > MAX_SHOWN
              ? t('cases_for_module.see_all_n', {
                  defaultValue: 'See all {{count}} cases',
                  count: cases.length,
                })
              : t('cases_for_module.see_all', {
                  defaultValue: 'Open the case library',
                })}
            <ArrowRight size={12} aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}
