// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { demosForMarket, type DemoCatalogRow } from './flagshipDemos';

/**
 * Ready-to-install starting points for the chosen market. One click installs
 * and opens the project.
 *
 * @param country lower-case ISO 3166-1 alpha-2 of the market the reader chose.
 */
export function FlagshipDemoCards({ country }: { country: string | null }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [busyId, setBusyId] = useState<string | null>(null);
  const { data: catalog } = useQuery({
    queryKey: ['demo-catalog'],
    queryFn: () => apiGet<DemoCatalogRow[]>('/demo/catalog').catch(() => []),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const { demos, matched } = demosForMarket(country, catalog ?? []);

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
        {matched
          ? t('onboarding.flagship_lede_market', {
              defaultValue: 'Sample projects from your market, ready to open.',
            })
          : t('onboarding.flagship_lede_global', {
              defaultValue: 'No sample project for your market yet. This one shows the whole platform.',
            })}
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {demos.map((d) => {
          const k = d.key ? `onboarding.flagship_${d.key}` : null;
          return (
            <article key={d.id} data-testid={`flagship-card-${d.id}`} className="flex flex-col rounded-xl border border-border-light p-4">
              {d.tag && (
                <span className="text-2xs font-semibold uppercase tracking-wide text-oe-blue-text">
                  {k ? t(`${k}_tag`, { defaultValue: d.tag }) : d.tag}
                </span>
              )}
              <h4 className="mt-1 text-sm font-bold text-content-primary">
                {k ? t(`${k}_title`, { defaultValue: d.title }) : d.title}
              </h4>
              {d.forWho && (
                <p className="text-xs text-content-secondary">
                  {k ? t(`${k}_for`, { defaultValue: d.forWho }) : d.forWho}
                </p>
              )}
              <ul className="mt-2 flex-1 list-disc space-y-0.5 pl-4 text-xs text-content-tertiary">
                {d.points.map((p, i) => (
                  <li key={i}>{k ? t(`${k}_p${i + 1}`, { defaultValue: p }) : p}</li>
                ))}
              </ul>
              <button
                type="button"
                data-testid={`flagship-install-${d.id}`}
                disabled={busyId !== null}
                aria-busy={busyId === d.id}
                onClick={() => void install(d.id)}
                className="mt-3 inline-flex items-center justify-center gap-2 rounded-lg bg-oe-blue px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60"
              >
                {busyId === d.id && <Loader2 size={12} className="animate-spin" aria-hidden="true" />}
                {busyId === d.id
                  ? t('onboarding.installing_label', { defaultValue: 'Installing…' })
                  : t('onboarding.flagship_install', { defaultValue: 'Install and open' })}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
