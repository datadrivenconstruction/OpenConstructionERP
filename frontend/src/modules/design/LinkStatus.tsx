// Design module (ERP side of the design editor link).
/** Which editors are linked to the project, when each last called, what waits for a decision; unlink one. */

import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Unlink } from 'lucide-react';
import { Button, Card, CardHeader } from '@/shared/ui';
import { fetchLinkStatus, revokeEditor } from './linksApi';
import { tr } from './BriefFields';

const when = (iso: string | null, lang: string): string =>
  iso ? new Date(iso).toLocaleString(lang, { dateStyle: 'medium', timeStyle: 'short' }) : '';

export function LinkStatus({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const key = ['design-link-status', projectId];
  const status = useQuery({ queryKey: key, queryFn: () => fetchLinkStatus(projectId), refetchInterval: 60_000, retry: false });
  const revoke = useMutation({
    mutationFn: (id: string) => revokeEditor(projectId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });
  if (!status.data) return null;
  const { editors, pending_revisions: pending, last_revision: lastRev } = status.data;
  const lang = i18n.language;

  return (
    <Card padding="none">
      <CardHeader className="px-4 pt-4 pb-3" title={tr(t, 'design.link_status.title')} />
      <div className="flex flex-col gap-2 px-4 pb-4 text-sm" data-testid="link-status">
        <p role="status" data-testid="link-state">
          {editors.length > 0 ? tr(t, 'design.link_status.connected', { n: editors.length }) : tr(t, 'design.link_status.none')}
        </p>
        {editors.map((e) => (
          <div key={e.id} data-testid="link-editor" className="flex flex-wrap items-center justify-between gap-2 rounded border border-border-light px-3 py-2">
            <div>
              <p className="font-medium">{[e.client_name || tr(t, 'design.link_status.editor'), e.client_version].filter(Boolean).join(' ')}</p>
              <p className="text-content-secondary">
                {e.last_used_at
                  ? tr(t, 'design.link_status.last_sync', { when: when(e.last_used_at, lang) })
                  : tr(t, 'design.link_status.never_used')}
                {' · '}
                {tr(t, 'design.link_status.expires', { when: when(e.expires_at, lang) })}
              </p>
            </div>
            <Button variant="secondary" icon={<Unlink size={14} />} loading={revoke.isPending && revoke.variables === e.id} onClick={() => revoke.mutate(e.id)}>
              {tr(t, 'design.link_status.revoke')}
            </Button>
          </div>
        ))}
        {lastRev && (
          <p data-testid="link-last-revision" className="text-content-secondary" title={lastRev.package_sha256}>
            {tr(t, 'design.link_status.last_revision_by', { number: lastRev.number, who: lastRev.author ?? '', when: when(lastRev.received_at, lang) })}
            {' · '}
            <Link className="text-oe-blue-text underline" to="/design/revisions">{tr(t, 'design.revisions.nav')}</Link>
          </p>
        )}
        {pending > 0 && (
          <p data-testid="link-pending">
            <Link className="text-oe-blue-text underline" to="/design/acceptance">
              {tr(t, 'design.link_status.pending', { n: pending })}
            </Link>
          </p>
        )}
      </div>
    </Card>
  );
}
