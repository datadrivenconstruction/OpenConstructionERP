// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { FLAGSHIP_DEMOS } from './flagshipDemos';

/** Four ready-to-install starting points. One click installs and opens the project. */
export function FlagshipDemoCards() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [busyId, setBusyId] = useState<string | null>(null);

  const install = async (id: string) => {
    if (busyId) return;
    setBusyId(id);
    try {
      const res = await apiPost<{ project_id: string }>(`/demo/install/${id}`, undefined, {
        longRunning: true,
      });
      navigate(`/projects/${res.project_id}`);
    } catch {
      addToast({
        type: 'error',
        title: t('onboarding.demo_install_error', { defaultValue: 'Failed to install demo project' }),
      });
      setBusyId(null);
    }
  };

  return (
    <section
      data-testid="flagship-demos"
      className="rounded-2xl bg-surface-elevated p-6 shadow-sm shadow-black/[0.04]"
    >
      <h3 className="text-base font-bold text-content-primary">
        {t('onboarding.flagship_title', { defaultValue: 'Start from a ready-made project' })}
      </h3>
      <p className="mt-1 text-xs text-content-tertiary">
        {t('onboarding.flagship_lede', {
          defaultValue: 'Four sample projects from Saudi Arabia, each set up for a different kind of company.',
        })}
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {FLAGSHIP_DEMOS.map((d) => {
          const k = `onboarding.flagship_${d.key}`;
          return (
            <article key={d.id} className="flex flex-col rounded-xl border border-border-light p-4">
              <span className="text-2xs font-semibold uppercase tracking-wide text-oe-blue-text">
                {t(`${k}_tag`, { defaultValue: d.tag })}
              </span>
              <h4 className="mt-1 text-sm font-bold text-content-primary">
                {t(`${k}_title`, { defaultValue: d.title })}
              </h4>
              <p className="text-xs text-content-secondary">{t(`${k}_for`, { defaultValue: d.forWho })}</p>
              <ul className="mt-2 flex-1 list-disc space-y-0.5 pl-4 text-xs text-content-tertiary">
                {d.points.map((p, i) => (
                  <li key={i}>{t(`${k}_p${i + 1}`, { defaultValue: p })}</li>
                ))}
              </ul>
              <button
                type="button"
                data-testid={`flagship-install-${d.id}`}
                disabled={busyId !== null}
                onClick={() => void install(d.id)}
                className="mt-3 inline-flex items-center justify-center gap-2 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
              >
                {busyId === d.id && <Loader2 size={12} className="animate-spin" />}
                {t('onboarding.flagship_install', { defaultValue: 'Install and open' })}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
