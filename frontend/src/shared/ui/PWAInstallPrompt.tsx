// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PWAInstallPrompt — discrete bottom-right install nudge.
 *
 * Behaviour:
 *   * Listens for ``beforeinstallprompt`` on the window and stashes the
 *     event so the user can trigger ``prompt()`` from our own button.
 *   * Renders only when (a) the event has fired AND (b) the user has
 *     not dismissed the prompt within the last 30 days, AND (c) the
 *     app is not already installed (``display-mode: standalone``).
 *   * On iOS Safari, ``beforeinstallprompt`` never fires. Instead we
 *     show a one-time hint instructing the user to use the Share menu
 *     → Add to Home Screen.  The hint is gated to iOS *Safari* (not
 *     iOS Chrome/Edge — those use the system WebKit but don't expose
 *     "Add to Home" in the share sheet).  User-agent sniffing is
 *     normally a smell, but iOS gives no other reliable signal here.
 *
 * Persistence:
 *   * ``oce.pwa.dismissedAt`` — ISO timestamp of last "Not now" click.
 *     Re-shown after 30 days.
 *   * ``oce.pwa.iosHintShown`` — "1" once the iOS hint has been seen
 *     and dismissed; never re-shown.
 *
 * Mounted exactly once in ``app/App.tsx``.
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, X, Share } from 'lucide-react';

/* ── localStorage keys & timing ──────────────────────────────────────── */

const DISMISS_KEY = 'oce.pwa.dismissedAt';
const IOS_HINT_KEY = 'oce.pwa.iosHintShown';
const DISMISS_COOLDOWN_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

/* ── beforeinstallprompt event shape (not in DOM lib yet) ─────────────── */

interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
  prompt(): Promise<void>;
}

/* ── small helpers ───────────────────────────────────────────────────── */

function isIosSafari(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  const ua = navigator.userAgent || '';
  // iPhone / iPad / iPod
  const isIos = /iPad|iPhone|iPod/.test(ua) || (
    navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1
  );
  if (!isIos) return false;
  // Mobile Safari only — exclude CriOS (iOS Chrome), FxiOS (iOS Firefox),
  // EdgiOS (iOS Edge) which can't add a PWA from the share sheet.
  if (/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua)) return false;
  return /Safari/.test(ua);
}

function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  // Chrome/Edge/Firefox path
  if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) {
    return true;
  }
  // iOS path (legacy navigator.standalone)
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return nav.standalone === true;
}

function isLocalDev(): boolean {
  // Suppress the install nudge during local development — the prompt is
  // confusing for devs running `npm run dev` against a Vite server, and
  // an installed PWA pointing at localhost is not a useful artefact.
  if (import.meta.env.DEV) return true;
  if (typeof window === 'undefined') return false;
  const host = window.location.hostname;
  return host === 'localhost' || host === '127.0.0.1' || host === '[::1]' || host === '::1';
}

function dismissedRecently(): boolean {
  try {
    const raw = localStorage.getItem(DISMISS_KEY);
    if (!raw) return false;
    const ts = Date.parse(raw);
    if (Number.isNaN(ts)) return false;
    return Date.now() - ts < DISMISS_COOLDOWN_MS;
  } catch {
    return false;
  }
}

/* ── Component ───────────────────────────────────────────────────────── */

export function PWAInstallPrompt() {
  const { t } = useTranslation();
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [iosHintVisible, setIosHintVisible] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [hidden, setHidden] = useState(true);

  // Listen for the install prompt event (Chromium / Firefox).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isStandalone()) return;
    if (isLocalDev()) return;

    const handler = (e: Event) => {
      // Prevent Chrome's mini-infobar; we'll show our own UI instead.
      e.preventDefault();
      if (dismissedRecently()) return;
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      setHidden(false);
    };

    const installedHandler = () => {
      setDeferredPrompt(null);
      setHidden(true);
    };

    window.addEventListener('beforeinstallprompt', handler);
    window.addEventListener('appinstalled', installedHandler);
    return () => {
      window.removeEventListener('beforeinstallprompt', handler);
      window.removeEventListener('appinstalled', installedHandler);
    };
  }, []);

  // Show iOS Safari hint once (no beforeinstallprompt on iOS).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (isStandalone()) return;
    if (isLocalDev()) return;
    if (!isIosSafari()) return;
    try {
      if (localStorage.getItem(IOS_HINT_KEY) === '1') return;
    } catch {
      // localStorage unavailable — don't show, can't persist dismissal.
      return;
    }
    setIosHintVisible(true);
    setHidden(false);
  }, []);

  const handleInstall = useCallback(async () => {
    if (!deferredPrompt) return;
    setInstalling(true);
    try {
      await deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      if (choice.outcome === 'dismissed') {
        try { localStorage.setItem(DISMISS_KEY, new Date().toISOString()); } catch { /* ignore */ }
      }
    } catch {
      // Browser refused prompt() (already shown once, etc.) — silent.
    } finally {
      setDeferredPrompt(null);
      setHidden(true);
      setInstalling(false);
    }
  }, [deferredPrompt]);

  const handleDismiss = useCallback(() => {
    try { localStorage.setItem(DISMISS_KEY, new Date().toISOString()); } catch { /* ignore */ }
    setDeferredPrompt(null);
    setHidden(true);
  }, []);

  const handleDismissIosHint = useCallback(() => {
    try { localStorage.setItem(IOS_HINT_KEY, '1'); } catch { /* ignore */ }
    setIosHintVisible(false);
    setHidden(true);
  }, []);

  if (hidden) return null;

  // iOS hint variant — no programmatic install, just an instruction.
  if (iosHintVisible) {
    return (
      <div
        role="dialog"
        aria-live="polite"
        aria-label={t('pwa.install_prompt_title', { defaultValue: 'Install OCERP' })}
        data-testid="pwa-install-prompt-ios"
        className="oe-dock-aware fixed bottom-4 right-4 z-[60] flex max-w-sm items-start gap-3 rounded-xl border border-border-light bg-surface-elevated p-3 shadow-lg backdrop-blur-sm"
      >
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <Share size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-content-primary">
            {t('pwa.install_prompt_title', { defaultValue: 'Install OCERP for offline access' })}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-content-secondary">
            {t('pwa.ios_hint_body', {
              defaultValue:
                'Tap the Share icon in Safari, then choose "Add to Home Screen" to install OCERP.',
            })}
          </p>
          <div className="mt-2.5 flex justify-end gap-2">
            <button
              type="button"
              onClick={handleDismissIosHint}
              className="rounded-md px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
            >
              {t('pwa.not_now_button', { defaultValue: 'Got it' })}
            </button>
          </div>
        </div>
        <button
          type="button"
          onClick={handleDismissIosHint}
          aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
          className="shrink-0 rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  // Native install variant
  if (!deferredPrompt) return null;
  return (
    <div
      role="dialog"
      aria-live="polite"
      aria-label={t('pwa.install_prompt_title', { defaultValue: 'Install OCERP' })}
      data-testid="pwa-install-prompt"
      className="oe-dock-aware fixed bottom-4 right-4 z-[60] flex max-w-sm items-start gap-3 rounded-xl border border-border-light bg-surface-elevated p-3 shadow-lg backdrop-blur-sm"
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
        <Download size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-content-primary">
          {t('pwa.install_prompt_title', { defaultValue: 'Install OCERP for offline access' })}
        </p>
        <p className="mt-1 text-xs leading-relaxed text-content-secondary">
          {t('pwa.install_prompt_body', {
            defaultValue:
              'Add OCERP to your device for a faster launch, offline app shell and a native-feel field experience.',
          })}
        </p>
        <div className="mt-2.5 flex justify-end gap-2">
          <button
            type="button"
            onClick={handleDismiss}
            disabled={installing}
            className="rounded-md px-2.5 py-1 text-xs font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-60"
          >
            {t('pwa.not_now_button', { defaultValue: 'Not now' })}
          </button>
          <button
            type="button"
            onClick={handleInstall}
            disabled={installing}
            className="inline-flex items-center gap-1 rounded-md bg-oe-blue px-2.5 py-1 text-xs font-semibold text-white hover:bg-oe-blue/90 disabled:opacity-60"
          >
            <Download size={12} />
            {t('pwa.install_button', { defaultValue: 'Install' })}
          </button>
        </div>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        disabled={installing}
        className="shrink-0 rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-60"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export default PWAInstallPrompt;
