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
import { AlertTriangle, X, Download, ExternalLink } from 'lucide-react';

const SESSION_KEY = 'oe_demo_modal_dismissed';

export function DemoBanner() {
  const [demoMode, setDemoMode] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/system/status')
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return;
        if (data?.demo_mode === true) {
          setDemoMode(true);
          // Show the full modal once per session
          if (sessionStorage.getItem(SESSION_KEY) !== '1') {
            setModalOpen(true);
          }
        }
      })
      .catch(() => {
        // Network or backend error — silently skip the banner
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const closeModal = () => {
    sessionStorage.setItem(SESSION_KEY, '1');
    setModalOpen(false);
  };

  if (!demoMode) return null;

  return (
    <>
      {/* Persistent thin strip at the very top */}
      <div
        role="alert"
        className="sticky top-0 z-50 flex items-center justify-center gap-2 px-4 py-1.5 text-xs font-medium text-amber-950 bg-gradient-to-r from-amber-300 via-amber-200 to-amber-300 border-b border-amber-500/40 shadow-sm"
      >
        <AlertTriangle size={13} className="shrink-0" />
        <span className="truncate">
          Public demo — do not upload real data. For production use, install
          locally:
        </span>
        <code className="px-1.5 py-0.5 rounded bg-amber-900/15 text-amber-950 font-mono text-[11px]">
          pip install openconstructionerp
        </code>
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="ml-1 underline underline-offset-2 hover:text-amber-900"
        >
          Why?
        </button>
      </div>

      {/* One-time modal */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
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
                  This is a public demo
                </h2>
                <p className="text-xs text-content-tertiary mt-0.5">
                  Read this before you click around
                </p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                aria-label="Close"
                className="shrink-0 p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* Body */}
            <div className="px-6 pb-2 space-y-3 text-sm text-content-secondary leading-relaxed">
              <p>
                You're looking at the public hosted demo of{' '}
                <strong className="text-content-primary">
                  OpenConstructionERP
                </strong>
                . It runs on a single small VPS and is shared with everyone in
                the world who clicks the demo link, so:
              </p>
              <ul className="space-y-2 pl-1">
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-red-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      Do not upload real or confidential data.
                    </strong>{' '}
                    Anything you put here is visible to other demo visitors.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      Not every module is stable here.
                    </strong>{' '}
                    Heavy features (CAD/BIM conversion, AI inference, vector
                    search) are tuned for local installs and may be slow or
                    rate-limited on the demo.
                  </span>
                </li>
                <li className="flex gap-2.5">
                  <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5" />
                  <span>
                    <strong className="text-content-primary">
                      Install locally for real work.
                    </strong>{' '}
                    The full product runs on your own machine in two minutes.
                    Your data stays on your computer.
                  </span>
                </li>
              </ul>

              <div className="mt-4 rounded-lg bg-surface-secondary border border-border-light p-3">
                <div className="text-[10px] font-bold uppercase tracking-wider text-content-quaternary mb-1.5">
                  Install locally — 3 commands
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
                I understand, continue
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
