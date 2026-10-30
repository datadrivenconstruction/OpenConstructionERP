import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, FolderOpen, Loader2 } from 'lucide-react';
import { Breadcrumb, Card } from '@/shared/ui';
import { apiPost, API_BASE } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useThemeStore } from '@/stores/useThemeStore';
import {
  hostedSrc,
  parseGuestMessage,
  useRuntimeUiEntries,
  type HostContextMessage,
  type RuntimeUiEntry,
} from './runtimeModules';

interface UiToken {
  token: string;
  expires_at: string;
}

/**
 * Hosts the page of a ZIP-installed module inside the app shell.
 *
 * Embedded mode: the module's own HTML runs in a sandboxed iframe without
 * `allow-same-origin`, so it cannot read the shell's storage or cookies. It
 * gets project, theme, locale and a short-lived token that only opens its
 * own API, through the versioned postMessage bridge in `runtimeModules.ts`.
 */
export function RuntimeModulePage() {
  const { moduleName = '' } = useParams<{ moduleName: string }>();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { data: entries, isLoading, isError } = useRuntimeUiEntries();
  const entry = entries?.find((e) => e.module === moduleName);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 p-8 text-content-secondary">
        <Loader2 size={16} className="animate-spin" />
        {t('module_packages.host_loading', { defaultValue: 'Loading module page...' })}
      </div>
    );
  }
  if (isError || !entry) {
    return (
      <Card className="m-6 p-6">
        <div className="flex items-start gap-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-warning" />
          <div>
            <p className="font-medium text-content-primary">
              {t('module_packages.host_missing_title', { defaultValue: 'This module page is not available' })}
            </p>
            <p className="mt-1 text-sm text-content-secondary">
              {t('module_packages.host_missing_body', {
                defaultValue: 'The module may be disabled or uninstalled. An administrator can check it under Modules, System Modules.',
              })}
            </p>
            <button type="button" className="mt-3 text-sm text-oe-blue hover:underline" onClick={() => navigate('/modules?tab=system')}>
              {t('module_packages.host_open_modules', { defaultValue: 'Open Modules' })}
            </button>
          </div>
        </div>
      </Card>
    );
  }
  return <HostedFrame key={entry.module} entry={entry} locale={i18n.language} />;
}

function HostedFrame({ entry, locale }: { entry: RuntimeUiEntry; locale: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const theme = useThemeStore((s) => s.resolved);
  const [title, setTitle] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const readyRef = useRef(false);

  const sendContext = useCallback(async () => {
    const frame = frameRef.current?.contentWindow;
    if (!frame || !readyRef.current) return;
    try {
      const issued = await apiPost<UiToken>(`/v1/module-packages/ui-token/${entry.module}`);
      const message: HostContextMessage = {
        oe: 'context',
        v: 1,
        module: entry.module,
        project_id: projectId,
        theme,
        locale,
        api_base: `${window.location.origin}${API_BASE}`,
        token: issued.token,
        token_expires_at: issued.expires_at,
      };
      // The sandboxed frame has an opaque origin, so '*' is the only target that
      // reaches it; the recipient is pinned by sending to this exact contentWindow.
      frame.postMessage(message, '*');
    } catch {
      setFailed(true);
    }
  }, [entry.module, projectId, theme, locale]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frameRef.current?.contentWindow) return;
      const msg = parseGuestMessage(event.data);
      if (!msg) return;
      if (msg.oe === 'ready' || msg.oe === 'token') {
        readyRef.current = true;
        void sendContext();
      } else if (msg.oe === 'navigate') {
        navigate(msg.to);
      } else if (msg.oe === 'title') {
        setTitle(msg.title);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [sendContext, navigate]);

  // Project, theme or locale changed: tell a page that already said hello.
  useEffect(() => {
    void sendContext();
  }, [sendContext]);

  const needsProject = Boolean(entry.project_param) && !projectId;

  return (
    <div className="flex h-full min-h-[70vh] flex-col gap-3 p-4">
      <Breadcrumb items={[{ label: t('nav.modules', { defaultValue: 'Modules' }), to: '/modules' }, { label: title ?? entry.label }]} />
      <div className="flex items-center gap-2">
        <h1 className="text-lg font-semibold text-content-primary">{title ?? entry.label}</h1>
        <span className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-tertiary">
          {t('module_packages.mode_hosted', { defaultValue: 'Embedded page' })}
        </span>
      </div>
      {failed && (
        <p className="text-sm text-semantic-error">
          {t('module_packages.host_token_failed', { defaultValue: 'The module page could not be signed in. Reload to try again.' })}
        </p>
      )}
      {needsProject ? (
        <Card className="p-6">
          <div className="flex items-center gap-3 text-content-secondary">
            <FolderOpen size={18} />
            {t('module_packages.host_pick_project', { defaultValue: 'Select a project in the top bar to open this module.' })}
          </div>
        </Card>
      ) : (
        <iframe
          ref={frameRef}
          title={entry.label}
          src={hostedSrc(entry, projectId)}
          sandbox="allow-scripts allow-forms allow-downloads allow-popups"
          referrerPolicy="no-referrer"
          className="w-full flex-1 rounded-lg border border-border bg-surface-primary"
        />
      )}
    </div>
  );
}

export default RuntimeModulePage;
