// Design module (ERP side of the design editor link).
/**
 * Design → Editor: the one button. It asks the ERP for a one-use link code and saves it as a `.ddclink` file;
 * opening that file in the design editor opens the project there. If the editor is not installed, the
 * installer address is shown once.
 */

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Download, ExternalLink, FolderOpen, PencilRuler, FilePlus, RefreshCw } from 'lucide-react';
import { Button, Card, CardHeader, EmptyState, PageHeader } from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { createLink, fetchAccess, fetchRevisions } from './api';
import { LinkStatus } from './LinkStatus';
import { EDITOR_SITE, INSTALLER_SEEN_KEY, installerUrl, linkExpired, linkFileName, serializeLink, type LinkFile } from './data/offer';
import { linkFailure, minutesLeft, type LinkFailure } from './data/linkErrors';
import { tr } from './BriefFields';
import { desktopEditor, errorText, type Install, type Launch } from './desktopEditor';

const read = (key: string): string | null => {
  try { return localStorage.getItem(key); } catch { return null; }
};
const write = (key: string, value: string): void => {
  try { localStorage.setItem(key, value); } catch { /* private mode: the hint just shows again */ }
};

/** Hand a string to the browser as a file download. */
export function saveText(name: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function EditorLinkPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState
        icon={<FolderOpen size={28} aria-hidden />}
        title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.editor.no_project_hint')}
      />
    );
  }
  return <EditorLink key={projectId} projectId={projectId} />;
}

function EditorLink({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const project = useQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId) });
  const [last, setLast] = useState<LinkFile | null>(null);
  // Shown on the first visit only; the flag is written on mount so a reload does not show it again.
  const [hintSeen] = useState(() => read(INSTALLER_SEEN_KEY) === '1');
  const installer = installerUrl(import.meta.env as Record<string, string | undefined>);
  const revisions = useQuery({ queryKey: ['design-revisions', projectId], queryFn: () => fetchRevisions(projectId) });
  // Who has the project open in the editor right now; a failed read just hides the line.
  const access = useQuery({ queryKey: ['design-access', projectId], queryFn: () => fetchAccess(projectId), retry: false });
  const [failure, setFailure] = useState<LinkFailure | null>(null);
  const lastAction = useRef<'new' | 'open'>('open');
  const [now, setNow] = useState(() => Date.now());

  const desktop = desktopEditor();
  // Desktop app: the link goes straight to the editor the shell installed; nothing is saved to Downloads.
  const [needs, setNeeds] = useState<null | { kind: 'install' | 'launch' | 'local'; reason: string }>(null);
  const [missing, setMissing] = useState(false);
  const [started, setStarted] = useState(false);
  const [localPath, setLocalPath] = useState('');
  const [installedName, setInstalledName] = useState<string | null>(null);
  const [pendingLink, setPendingLink] = useState<LinkFile | null>(null);

  const report = (err: unknown) => {
    addToast({ type: 'error', title: tr(t, 'design.editor.desktop_failed'), message: errorText(err) });
    setFailure({ key: 'design.editor.err_desktop', retry: false });
  };
  const afterLaunch = (out: Launch) => {
    setNeeds(null);
    setMissing(out.result === 'not_installed');
    setStarted(out.result === 'started');
    if (out.result === 'needs_confirmation') setNeeds({ kind: 'launch', reason: out.reason });
  };
  const afterInstall = (kind: 'install' | 'local') => (out: Install) => {
    if (out.result === 'needs_confirmation') {
      setNeeds({ kind, reason: out.reason });
      return;
    }
    setNeeds(null);
    setMissing(false);
    setInstalledName(out.name);
    // The person pressed "Open" before installing: finish that, do not make them press it again.
    if (pendingLink && !linkExpired(pendingLink)) launch.mutate({ link: pendingLink, confirmed: false });
    else make.mutate(lastAction.current);
  };
  const launch = useMutation({
    mutationFn: ({ link, confirmed }: { link: LinkFile; confirmed: boolean }) => desktop!.launch(serializeLink(link), confirmed),
    onSuccess: afterLaunch,
    onError: report,
  });
  const download = useMutation({ mutationFn: (confirmed: boolean) => desktop!.download(confirmed), onSuccess: afterInstall('install'), onError: report });
  const local = useMutation({
    mutationFn: ({ confirmed }: { confirmed: boolean }) => desktop!.installLocal(localPath.trim(), confirmed),
    onSuccess: afterInstall('local'),
    onError: report,
  });

  const make = useMutation({
    // "Open" continues from the newest revision; a project without one starts a new design.
    mutationFn: async (action: 'new' | 'open') => {
      lastAction.current = action;
      setFailure(null);
      if (action === 'new') return createLink(projectId, 'new');
      const latest = (await fetchRevisions(projectId)).reduce<{ revision_id: string; number: number } | null>(
        (best, r) => (!best || r.number > best.number ? r : best),
        null,
      );
      return latest ? createLink(projectId, 'open', latest.revision_id) : createLink(projectId, 'new');
    },
    onSuccess: (link) => {
      setLast(link);
      if (desktop) {
        setPendingLink(link);
        setStarted(false);
        launch.mutate({ link, confirmed: false });
        return;
      }
      saveText(linkFileName(link.project_name || project.data?.name || ''), serializeLink(link));
    },
    // Inline and lasting, not a toast: the sentence says what to do and the retry button sits beside it.
    onError: (err) => {
      setLast(null);
      setFailure(linkFailure(err));
    },
  });

  useEffect(() => {
    write(INSTALLER_SEEN_KEY, '1');
  }, []);
  // The expiry has to show without a click: tick while a link is waiting to be opened.
  useEffect(() => {
    if (!last) return;
    const id = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(id);
  }, [last]);

  const expired = last ? linkExpired(last, now) : false;
  const hasRevisions = (revisions.data?.length ?? 0) > 0;
  const lock = access.data?.lock ?? null;
  const showNext = !!last && !expired || started;

  return (
    <div className="flex max-w-3xl flex-col gap-5 animate-fade-in">
      <PageHeader srTitle={tr(t, 'design.editor.title')} subtitle={tr(t, 'design.editor.subtitle')} />
      <Card padding="none">
        <CardHeader className="px-4 pt-4 pb-3" title={project.data?.name ?? tr(t, 'design.editor.title')} subtitle={tr(t, 'design.editor.how')} />
        <div className="flex flex-col gap-3 px-4 pb-4">
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<PencilRuler size={16} />} loading={make.isPending} onClick={() => make.mutate('open')}>
              {tr(t, 'design.editor.open')}
            </Button>
            {hasRevisions && (
              <Button variant="secondary" icon={<FilePlus size={16} />} disabled={make.isPending} onClick={() => make.mutate('new')}>
                {tr(t, 'design.editor.new')}
              </Button>
            )}
          </div>
          {lock && (
            <p role="status" data-testid="editor-lock" className="text-sm text-content-secondary">
              {lock.mine ? tr(t, 'design.editor.lock_mine') : tr(t, 'design.editor.lock_held', { name: lock.held_by })}
            </p>
          )}
          {failure && (
            <div role="alert" data-testid="link-error" className="flex flex-col gap-2 rounded border border-semantic-error/40 bg-semantic-error-bg px-3 py-2 text-sm">
              <p className="font-medium">{tr(t, 'design.editor.failed')}</p>
              <p>{tr(t, failure.key)}</p>
              {failure.retry && (
                <div>
                  <Button variant="secondary" icon={<RefreshCw size={16} />} loading={make.isPending} onClick={() => make.mutate(lastAction.current)}>
                    {tr(t, 'design.editor.retry')}
                  </Button>
                </div>
              )}
            </div>
          )}
          {desktop && started && <p role="status" data-testid="desktop-started" className="text-sm">{tr(t, 'design.editor.desktop_started')}</p>}
          {desktop && installedName && !missing && <p role="status" className="text-sm">{tr(t, 'design.editor.desktop_installed', { name: installedName })}</p>}
          {desktop && missing && (
            <div data-testid="desktop-missing" className="flex flex-col gap-2 rounded border border-border-light bg-surface-secondary px-3 py-2 text-sm">
              <p>{tr(t, 'design.editor.desktop_missing')}</p>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" icon={<Download size={16} />} loading={download.isPending} onClick={() => download.mutate(false)}>
                  {tr(t, 'design.editor.desktop_download')}
                </Button>
              </div>
              <label className="flex flex-col gap-1">
                <span>{tr(t, 'design.editor.desktop_local_path')}</span>
                <input
                  className="rounded border border-border-light bg-surface-primary px-2 py-1"
                  value={localPath}
                  onChange={(e) => setLocalPath(e.target.value)}
                  aria-describedby="local-hint"
                />
              </label>
              <p id="local-hint" className="text-content-secondary">{tr(t, 'design.editor.desktop_local_hint')}</p>
              <div>
                <Button variant="secondary" disabled={!localPath.trim()} loading={local.isPending} onClick={() => local.mutate({ confirmed: false })}>
                  {tr(t, 'design.editor.desktop_local')}
                </Button>
              </div>
            </div>
          )}
          {desktop && needs && (
            <div role="alertdialog" aria-labelledby="unsigned-title" data-testid="desktop-unsigned" className="rounded border border-semantic-warning/50 bg-semantic-warning-bg px-3 py-2 text-sm">
              <p id="unsigned-title" className="font-medium">{tr(t, 'design.editor.desktop_unsigned_title')}</p>
              <p className="mt-1">{tr(t, 'design.editor.desktop_unsigned', { reason: needs.reason })}</p>
              <div className="mt-2">
                <Button
                  variant="primary"
                  autoFocus
                  onClick={() => {
                    if (needs.kind === 'launch' && pendingLink) launch.mutate({ link: pendingLink, confirmed: true });
                    else if (needs.kind === 'install') download.mutate(true);
                    else local.mutate({ confirmed: true });
                  }}
                >
                  {tr(t, 'design.editor.desktop_continue')}
                </Button>
              </div>
            </div>
          )}
          {last && !desktop && (
            <div className="flex flex-col gap-2">
              <p role="status" data-testid="link-saved" className="text-sm">
                {expired
                  ? tr(t, 'design.editor.expired')
                  : tr(t, 'design.editor.saved', { name: linkFileName(last.project_name), minutes: minutesLeft(last.expires_at, now) })}
              </p>
              <div className="flex flex-wrap gap-2">
                {expired ? (
                  <Button variant="primary" icon={<RefreshCw size={16} />} loading={make.isPending} onClick={() => make.mutate(lastAction.current)}>
                    {tr(t, 'design.editor.renew')}
                  </Button>
                ) : (
                  <Button variant="secondary" icon={<Download size={16} />} onClick={() => saveText(linkFileName(last.project_name || project.data?.name || ''), serializeLink(last))}>
                    {tr(t, 'design.editor.save_again')}
                  </Button>
                )}
              </div>
            </div>
          )}
          {showNext && (
            <p data-testid="link-next" className="text-sm text-content-secondary">
              {tr(t, 'design.editor.next')}{' '}
              <Link className="text-oe-blue-text underline" to="/design/revisions">{tr(t, 'design.revisions.nav')}</Link>
              {' · '}
              <Link className="text-oe-blue-text underline" to="/design/acceptance">{tr(t, 'design.acceptance.nav')}</Link>
            </p>
          )}
          {/* Always reachable; open by itself on the first visit. A person who closed the tab on the first visit finds it again. */}
          <details data-testid="installer-hint" open={!hintSeen} className="rounded border border-border-light bg-surface-secondary px-3 py-2 text-sm">
            <summary className="cursor-pointer">{tr(t, 'design.editor.no_editor')}</summary>
            <a data-testid="installer-link" className="mt-2 inline-flex items-center gap-1 text-oe-blue-text underline" href={installer} target="_blank" rel="noopener noreferrer">
              {tr(t, 'design.editor.get')} <ExternalLink size={14} aria-hidden />
            </a>
            <p className="mt-2 text-content-secondary">{tr(t, 'design.editor.installed_steps')}</p>
            <p className="mt-1 text-content-secondary">{tr(t, 'design.editor.update_hint')}</p>
          </details>
          <p data-testid="mcp-hint" className="text-xs text-content-secondary">{tr(t, 'design.editor.mcp_hint')}</p>
          <a data-testid="editor-site" className="inline-flex items-center gap-1 text-xs text-oe-blue-text underline" href={EDITOR_SITE} target="_blank" rel="noopener noreferrer">
            {tr(t, 'design.editor.site')} <ExternalLink size={12} aria-hidden />
          </a>
        </div>
      </Card>
      <LinkStatus projectId={projectId} />
    </div>
  );
}
