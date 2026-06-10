import { create } from 'zustand';

/**
 * Global, navigation-surviving state for a ready-made pack install that keeps
 * provisioning in the BACKGROUND after the user has already entered the app.
 *
 * The onboarding "Ready-made Pack" step applies the language and a minimal
 * workspace fast, routes the user straight into the dashboard, and then lets
 * the heavy steps (cost databases, modules, sample projects) finish on their
 * own. This store carries the live per-step progress so a small, non-blocking
 * banner mounted at the app root (see ``BackgroundInstallBanner``) can keep
 * updating and reveal items as they complete, no full-screen spinner.
 *
 * The driver (``startBackgroundReadyPackInstall`` in the onboarding wizard)
 * owns the SSE stream and writes here; this module is intentionally pure state
 * so it can be imported from anywhere without pulling in the wizard.
 */

/** One row of the background-install checklist. */
export type BgInstallStepStatus = 'pending' | 'running' | 'ok' | 'skipped' | 'error';

export interface BgInstallStep {
  /** Stable step id from the SSE stream (apply_pack / locale / cost_db / ...). */
  step: string;
  /** Localized label resolved by the driver at start time. */
  label: string;
  status: BgInstallStepStatus;
  /** Short human detail when a step finishes (e.g. "55,000 items", "2 projects"). */
  detail?: string;
}

export interface BackgroundInstall {
  /** Pack slug being installed. */
  slug: string;
  /** Country / workspace name for the banner title. */
  country: string;
  steps: BgInstallStep[];
  /** True while the stream is still running. */
  running: boolean;
  /** Set once the stream reaches its terminal ``done`` frame. */
  done: boolean;
  /** True when at least one step ended in ``error`` (banner turns amber). */
  hadError: boolean;
}

interface BackgroundInstallStore {
  install: BackgroundInstall | null;
  /** Begin tracking a new background install (replaces any previous one). */
  begin: (slug: string, country: string, steps: BgInstallStep[]) => void;
  /** Flip a single step to ``running``. */
  markRunning: (step: string) => void;
  /** Record a step's final status (+ optional human detail). */
  markDone: (step: string, status: BgInstallStepStatus, detail?: string) => void;
  /** Mark the whole stream finished. */
  finish: (hadError: boolean) => void;
  /** Clear the banner (user dismissed it, or it auto-cleared after success). */
  dismiss: () => void;
}

export const useBackgroundInstallStore = create<BackgroundInstallStore>((set) => ({
  install: null,

  begin: (slug, country, steps) =>
    set({
      install: {
        slug,
        country,
        steps: steps.map((s) => ({ ...s, status: s.status ?? 'pending' })),
        running: true,
        done: false,
        hadError: false,
      },
    }),

  markRunning: (step) =>
    set((state) => {
      if (!state.install) return state;
      return {
        install: {
          ...state.install,
          steps: state.install.steps.map((s) =>
            s.step === step ? { ...s, status: 'running' } : s,
          ),
        },
      };
    }),

  markDone: (step, status, detail) =>
    set((state) => {
      if (!state.install) return state;
      return {
        install: {
          ...state.install,
          steps: state.install.steps.map((s) =>
            s.step === step ? { ...s, status, detail: detail ?? s.detail } : s,
          ),
        },
      };
    }),

  finish: (hadError) =>
    set((state) => {
      if (!state.install) return state;
      return {
        install: { ...state.install, running: false, done: true, hadError },
      };
    }),

  dismiss: () => set({ install: null }),
}));
