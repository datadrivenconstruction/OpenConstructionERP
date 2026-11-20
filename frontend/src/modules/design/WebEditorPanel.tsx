// Design module (ERP side of the design editor link).
/**
 * The full browser editor on this server: what is installed, what the release feed offers, and the
 * download, update and removal a person starts. The light engine keeps working whatever this shows.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Trash2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { ApiError } from '@/shared/lib/api';
import { megabytes } from './data/webEditor';
import { forgetPayload } from './editorPayload';
import {
  busy, fetchWebEditorStatus, problemKey, removeWebEditor, startWebEditorInstall, WEB_EDITOR_KEY,
  type WebEditorStatus,
} from './webEditorApi';

function refusalCode(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const detail = (e.body as { detail?: { code?: string } } | null)?.detail;
  return detail?.code ?? null;
}

/** The sentence for the current state; null when there is nothing to say. */
export function statusLine(s: WebEditorStatus, t: (k: string, o?: Record<string, unknown>) => string): string | null {
  if (s.install.state === 'downloading') {
    return t('design.web_editor.downloading', { done: megabytes(s.install.done), total: megabytes(s.install.total) });
  }
  if (s.install.state === 'verifying') return t('design.web_editor.verifying');
  if (s.install.state === 'unpacking') return t('design.web_editor.unpacking');
  if (s.install.state === 'failed') return t(problemKey(s.install.error));
  if (s.installed?.problem) return t(problemKey(s.installed.problem));
  if (!s.signing.key && (s.feed.state === 'available' || s.signing.error)) {
    return t(problemKey(s.signing.error ?? 'no_key'));
  }
  if (s.feed.state === 'available' && s.feed.problem) return t(problemKey(s.feed.problem));
  if (s.feed.state !== 'available' && !s.installed) return t(`design.web_editor.feed.${s.feed.state}`);
  return null;
}

export function WebEditorPanel({ onChanged }: { onChanged?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: WEB_EDITOR_KEY,
    queryFn: fetchWebEditorStatus,
    refetchInterval: (q) => (busy(q.state.data) ? 1000 : false),
  });
  const settle = () => {
    forgetPayload();
    void qc.invalidateQueries({ queryKey: WEB_EDITOR_KEY });
    onChanged?.();
  };
  const install = useMutation({ mutationFn: startWebEditorInstall, onSuccess: (s) => qc.setQueryData(WEB_EDITOR_KEY, s), onSettled: settle });
  const remove = useMutation({ mutationFn: removeWebEditor, onSettled: settle });

  const s = status.data;
  if (status.isLoading) return null;
  if (!s) {
    return <p className="text-xs text-content-tertiary" data-testid="web-editor-status">{t('design.web_editor.status_unavailable')}</p>;
  }
  const line = statusLine(s, t);
  const refused = refusalCode(install.error ?? remove.error);
  const offerable = s.can_install && s.feed.state === 'available' && !s.feed.problem && !busy(s)
    && (!s.installed || s.update_available);

  return (
    <section className="flex flex-col gap-2 text-sm" data-testid="web-editor-panel" aria-live="polite">
      <h3 className="text-sm font-semibold text-content-primary">{t('design.web_editor.title')}</h3>
      <p className="text-content-secondary">
        {s.installed
          ? t('design.web_editor.installed', { version: s.installed.version, size: megabytes(s.installed.bytes) })
          : t('design.web_editor.engine_only')}
      </p>
      {line && <p className="text-xs text-content-secondary" data-testid="web-editor-status">{line}</p>}
      {refused && <p role="alert" className="text-xs text-semantic-error">{t(problemKey(refused))}</p>}
      {busy(s) && (
        <progress className="h-1.5 w-full" max={s.install.total || 1} value={s.install.done}
          aria-label={t('design.web_editor.title')} />
      )}
      <div className="flex flex-wrap items-center gap-2">
        {offerable && (
          <Button size="sm" variant="primary" data-testid="web-editor-install" disabled={install.isPending}
            onClick={() => install.mutate()}>
            {install.isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Download size={14} aria-hidden />}
            {s.installed
              ? t('design.web_editor.update', { version: s.feed.version })
              : t('design.web_editor.install', { size: megabytes(s.feed.bytes ?? 0) })}
          </Button>
        )}
        {s.installed && s.can_remove && !busy(s) && (
          <Button size="sm" variant="ghost" data-testid="web-editor-remove" disabled={remove.isPending}
            onClick={() => remove.mutate()}>
            <Trash2 size={14} aria-hidden />{t('design.web_editor.remove')}
          </Button>
        )}
      </div>
      {!s.can_install && s.signing.key && s.feed.state === 'available' && !s.installed && (
        <p className="text-xs text-content-tertiary">{t('design.web_editor.ask_editor')}</p>
      )}
    </section>
  );
}
