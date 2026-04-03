/**
 * UpdateChecker — Shows update notification when a new version is available.
 *
 * In desktop mode (Tauri): uses tauri-plugin-updater to check GitHub Releases.
 * In browser mode: checks /api/system/status for version and compares with GitHub.
 *
 * UI: Small banner at top of page or badge on Settings, like Claude App.
 */

import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, X, CheckCircle2 } from 'lucide-react';
import { Button } from './Button';

const CURRENT_VERSION = '0.1.0';
const CHECK_INTERVAL = 4 * 60 * 60 * 1000; // 4 hours
const GITHUB_API = 'https://api.github.com/repos/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR/releases/latest';

interface UpdateInfo {
  version: string;
  notes: string;
  url: string;
}

function isTauri(): boolean {
  return !!(window as any).__TAURI__;
}

export function UpdateChecker() {
  const { t } = useTranslation();
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installed, setInstalled] = useState(false);

  const checkForUpdate = useCallback(async () => {
    try {
      if (isTauri()) {
        // Tauri native updater — dynamic import only in Tauri context
        try {
          const mod = await (Function('return import("@tauri-apps/plugin-updater")')() as Promise<any>);
          const result = await mod.check();
          if (result?.available) {
            setUpdate({
              version: result.version,
              notes: result.body ?? '',
              url: '',
            });
          }
        } catch { /* Tauri plugin not available */ }
      } else {
        // Browser mode: check GitHub releases
        const resp = await fetch(GITHUB_API);
        if (resp.ok) {
          const data = await resp.json();
          const latest = (data.tag_name ?? '').replace(/^v/, '');
          if (latest && latest !== CURRENT_VERSION) {
            setUpdate({
              version: latest,
              notes: data.body ?? '',
              url: data.html_url ?? '',
            });
          }
        }
      }
    } catch {
      // Silent fail — update check is optional
    }
  }, []);

  useEffect(() => {
    // Check on mount (with 5s delay to not block startup)
    const timer = setTimeout(checkForUpdate, 5000);
    // Check periodically
    const interval = setInterval(checkForUpdate, CHECK_INTERVAL);
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [checkForUpdate]);

  const handleInstall = useCallback(async () => {
    if (!isTauri()) {
      // Browser: open GitHub releases page
      if (update?.url) window.open(update.url, '_blank');
      return;
    }

    setInstalling(true);
    try {
      const updaterMod = await (Function('return import("@tauri-apps/plugin-updater")')() as Promise<any>);
      const processMod = await (Function('return import("@tauri-apps/plugin-process")')() as Promise<any>);
      const result = await updaterMod.check();
      if (result?.available) {
        await result.downloadAndInstall();
        setInstalled(true);
        setTimeout(() => processMod.relaunch(), 1500);
      }
    } catch {
      setInstalling(false);
    }
  }, [update]);

  if (!update || dismissed) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[100] flex items-center justify-center px-4 py-2 bg-gradient-to-r from-oe-blue to-violet-600 text-white text-sm shadow-lg animate-slide-down">
      <div className="flex items-center gap-3 max-w-2xl">
        {installed ? (
          <>
            <CheckCircle2 size={16} />
            <span className="font-medium">
              {t('update.installed', { defaultValue: 'Update installed! Restarting...' })}
            </span>
          </>
        ) : (
          <>
            <Download size={16} />
            <span>
              {t('update.available', {
                defaultValue: 'OpenConstructionERP {{version}} is available',
                version: update.version,
              })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleInstall}
              loading={installing}
              className="!text-white !border-white/30 hover:!bg-white/10"
            >
              {isTauri()
                ? t('update.install_restart', { defaultValue: 'Install & Restart' })
                : t('update.view_release', { defaultValue: 'View Release' })
              }
            </Button>
            <button
              onClick={() => setDismissed(true)}
              className="p-1 rounded hover:bg-white/10 transition-colors"
            >
              <X size={14} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
