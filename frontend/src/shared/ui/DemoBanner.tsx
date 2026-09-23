// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DemoBanner — persistent warning banner shown only on the public hosted
 * demo (https://openconstructionerp.com), driven by the backend's
 * `OE_DEMO_MODE=true` env var. Tells visitors:
 *
 *   1. This is a demo. Do not upload real data or confidential documents.
 *   2. Not all modules are stable here — install locally for production work.
 *
 * Two visual layers:
 *   - A thin amber strip at the very top of every page (always visible).
 *   - A one-time modal on first page load per session, with full explanation.
 *
 * Both are hidden when the backend reports `demo_mode: false` (every fresh
 * local install). No render cost for non-demo deployments.
 */

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Gauge, X, Download, ExternalLink } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';

const SESSION_KEY = 'oe_demo_modal_dismissed';

export function DemoBanner() {
  const { t } = useTranslation();
  const [modalOpen, setModalOpen] = useState(false);

  // Reuse the shared ['system-status'] query so DashboardPage and this banner
  // share a single network call instead of firing /api/system/status twice on
  // every page render. ``staleTime: Infinity`` is fine — demo_mode is fixed
  // for the life of the deployment and the query is invalidated on logout.
  const { data } = useQuery<{ demo_mode?: boolean }>({
    queryKey: ['system-status'],
    queryFn: () => apiGet<{ demo_mode?: boolean }>('/system/status'),
    retry: false,
    staleTime: Infinity,
  });
  const demoMode = data?.demo_mode === true;

  useEffect(() => {
    if (demoMode && sessionStorage.getItem(SESSION_KEY) !== '1') {
      setModalOpen(true);
    }
  }, [demoMode]);

  const closeModal = () => {
    sessionStorage.setItem(SESSION_KEY, '1');
    setModalOpen(false);
  };

  if (!demoMode) return null;

  return (
    <>
      {/* Persistent strip at the very top */}
      <div
        role="alert"
        className="sticky top-0 z-50 flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5 px-4 py-2.5 text-[13px] font-medium text-amber-950 bg-gradient-to-r from-amber-300 via-amber-200 to-amber-300 border-b border-amber-500/40 shadow-sm dark:text-amber-100 dark:from-amber-900/40 dark:via-amber-800/40 dark:to-amber-900/40 dark:border-amber-500/30"
      >
        <span className="flex items-center gap-2">
          <AlertTriangle size={14} className="shrink-0" />
          <span>
            {t('demo_banner.strip_no_real_data')}
          </span>
        </span>
        {/* Performance / sample-data caveat — always visible, not just in the modal */}
        <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-amber-900/10 dark:bg-amber-100/10 text-[12px]">
          <Gauge size={12} className="shrink-0 text-amber-700 dark:text-amber-300" />
          <span className="text-amber-900 dark:text-amber-200">
            {t('demo_banner.strip_perf_caveat')}
          </span>
        </span>
        <code className="px-1.5 py-0.5 rounded bg-amber-900/15 text-amber-950 font-mono text-[11px] dark:bg-amber-100/10 dark:text-amber-100">
          pip install openconstructionerp
        </code>
        <span className="flex items-center gap-2.5">
          <span className="opacity-80">{t('demo_banner.strip_or_download')}</span>
          <a
            href="https://openconstructionerp.com/download"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-50"
          >
            <Download size={12} className="shrink-0" />
            Windows
          </a>
          <a
            href="https://openconstructionerp.com/download"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-50"
          >
            macOS
          </a>
          <a
            href="https://openconstructionerp.com/download"
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-50"
          >
            Linux
          </a>
        </span>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-50"
        >
          {t('demo_banner.strip_why')}
        </button>
      </div>

      {/* One-time modal */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-lg p-4 animate-fade-in"
          onClick={closeModal}
        >
          <div
            className="relative w-full max-w-lg rounded-2xl bg-surface-primary border border-border-light shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start gap-3 px-6 pt-6 pb-3">
              <div className="shrink-0 w-11 h-11 rounded-full bg-amber-100 dark:bg-amber-950/40 flex items-center justify-center">
                <AlertTriangle size={22} className="text-amber-600 dark:text-amber-400" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-lg font-bold text-content-primary leading-tight">
                  {t('demo_banner.modal_title')}
                </h2>
                <p className="text-xs text-content-tertiary mt-0.5">
                  {t('demo_banner.modal_subtitle')}
                </p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="shrink-0 p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 pb-2 space-y-3 text-sm text-content-secondary leading-relaxed">
              {/* Sample-data callout — prominent, above the bullet list */}
              <div className="flex items-start gap-2.5 rounded-lg bg-blue-50 dark:bg-blue-950/30 border border-blue-200/60 dark:border-blue-500/20 px-3 py-2.5">
                <span className="shrink-0 mt-0.5 text-blue-600 dark:text-blue-400 font-bold text-xs uppercase tracking-wider">
                  {t('demo_banner.modal_sample_data_label')}
                </span>
                <span className="text-xs text-blue-800 dark:text-blue-300">
                  {t('demo_banner.modal_sample_data_body')}
                </span>
              </div>

              <p>
                {t('demo_banner.modal_intro_before_vps')}{' '}
                <strong className="text-content-primary">
                  OpenConstructionERP
                </strong>
                {'. '}{t('demo_banner.modal_intro_runs_on')}{' '}
                <strong className="text-content-primary">
                  {t('demo_banner.modal_intro_vps_spec')}
                </strong>{' '}
                {t('demo_banner.modal_intro_shared')}{' '}
                <strong className="text-content-primary">
                  {t('demo_banner.modal_intro_walkthrough')}
                </strong>{' '}
                {t('demo_banner.modal_intro_nothing_more')}
              </p>
              <ul className="space-y-2 pl-1">
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      {t('demo_banner.modal_bullet_no_data_heading')}
                    </strong>{' '}
                    {t('demo_banner.modal_bullet_no_data_body')}
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      {t('demo_banner.modal_bullet_perf_heading')}
                    </strong>{' '}
                    {t('demo_banner.modal_bullet_perf_body')}
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      {t('demo_banner.modal_bullet_install_heading')}
                    </strong>{' '}
                    {t('demo_banner.modal_bullet_install_body')}
                  </span>
                </li>
              </ul>

              <div className="mt-4 rounded-lg bg-surface-secondary border border-border-light p-3">
                <div className="text-[10px] font-bold uppercase tracking-wider text-content-quaternary mb-1.5">
                  {t('demo_banner.modal_install_box_label')}
                </div>
                <code className="block font-mono text-[12px] text-content-primary leading-relaxed">
                  pip install openconstructionerp
                  <br />
                  openestimate init-db
                  <br />
                  openestimate serve
                </code>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border-light">
              <a
                href="https://github.com/datadrivenconstruction/OpenConstructionERP"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-content-secondary hover:text-content-primary border border-border-light rounded-lg hover:bg-surface-secondary transition-colors"
              >
                <ExternalLink size={13} />
                GitHub
              </a>
              <a
                href="https://pypi.org/project/openconstructionerp/"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-content-secondary hover:text-content-primary border border-border-light rounded-lg hover:bg-surface-secondary transition-colors"
              >
                <Download size={13} />
                PyPI
              </a>
              <button
                type="button"
                onClick={closeModal}
                className="px-4 py-2 text-xs font-semibold text-white bg-oe-blue rounded-lg hover:bg-oe-blue-dark transition-colors"
              >
                {t('demo_banner.modal_cta')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
