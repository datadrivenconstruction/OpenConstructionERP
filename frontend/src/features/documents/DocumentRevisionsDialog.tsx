// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Revisions of one document and the RFIs, NCRs and change orders that point at it.
 *
 * The revision list shows which member of the chain is current and lets a user
 * promote an earlier one (the others become superseded in one step). The linked
 * records flag work raised against a revision that is no longer current, so a
 * reader sees an RFI that still points at an old drawing.
 */
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Badge } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchLinkedRecords,
  fetchRevisionChain,
  makeRevisionCurrent,
  type LinkedRecord,
} from './api';

interface Props {
  documentId: string;
  documentName: string;
  onClose: () => void;
}

function RecordGroup({ title, rows }: { title: string; rows: LinkedRecord[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return null;
  return (
    <div>
      <h4 className="oe-overline mb-1">{title}</h4>
      <ul className="divide-y divide-border-light rounded-lg border border-border-light">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
            <span className="font-mono text-xs text-content-tertiary">{r.number}</span>
            <span className="min-w-0 flex-1 truncate" title={r.title}>
              {r.title}
            </span>
            {r.on_superseded_revision && (
              <Badge variant="warning" size="sm">
                {t('documents.on_superseded_revision', { defaultValue: 'On a superseded revision' })}
              </Badge>
            )}
            <Badge variant="neutral" size="sm">
              {r.status}
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DocumentRevisionsDialog({ documentId, documentName, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const chainQuery = useQuery({
    queryKey: ['document-revision-chain', documentId],
    queryFn: () => fetchRevisionChain(documentId),
  });
  const linksQuery = useQuery({
    queryKey: ['document-linked-records', documentId],
    queryFn: () => fetchLinkedRecords(documentId),
  });

  const promote = useMutation({
    mutationFn: (id: string) => makeRevisionCurrent(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['document-revision-chain'] });
      void qc.invalidateQueries({ queryKey: ['document-linked-records'] });
      void qc.invalidateQueries({ queryKey: ['documents'] });
      addToast({ type: 'success', title: t('documents.revision_made_current', { defaultValue: 'Revision is now current' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const chain = chainQuery.data?.items ?? [];
  const links = linksQuery.data;
  const nothingLinked = !!links && links.rfis.length + links.ncrs.length + links.change_orders.length === 0;

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('documents.revisions_title', { defaultValue: 'Revisions and linked records' })}
      subtitle={documentName}
      size="lg"
      testId="document-revisions-dialog"
    >
      <div className="space-y-5">
        <div>
          <h4 className="oe-overline mb-1">{t('documents.revisions_heading', { defaultValue: 'Revisions' })}</h4>
          {chainQuery.isError ? (
            <p className="text-sm text-semantic-error">{getErrorMessage(chainQuery.error)}</p>
          ) : (
            <ul className="divide-y divide-border-light rounded-lg border border-border-light">
              {chain.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate" title={r.name}>
                    {r.revision_code
                      ? t('plan_room.revision', { defaultValue: 'Rev {{code}}', code: r.revision_code })
                      : t('plan_room.revision_none', { defaultValue: 'No revision number' })}
                    {' · '}
                    {r.name}
                  </span>
                  {r.is_current_revision ? (
                    <Badge variant="success" size="sm">
                      {t('plan_room.revision_current', { defaultValue: 'Current' })}
                    </Badge>
                  ) : (
                    <>
                      <Badge variant="warning" size="sm">
                        {t('plan_room.revision_superseded', { defaultValue: 'Superseded' })}
                      </Badge>
                      <button
                        type="button"
                        className="oe-btn-secondary text-xs"
                        disabled={promote.isPending}
                        onClick={() => promote.mutate(r.id)}
                      >
                        {t('documents.make_current', { defaultValue: 'Make current' })}
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h4 className="oe-overline mb-1">{t('documents.linked_records', { defaultValue: 'Linked records' })}</h4>
          {linksQuery.isError ? (
            <p className="text-sm text-semantic-error">{getErrorMessage(linksQuery.error)}</p>
          ) : nothingLinked ? (
            <p className="text-sm text-content-tertiary">
              {t('documents.no_linked_records', {
                defaultValue: 'No RFI, NCR or change order points at this document.',
              })}
            </p>
          ) : links ? (
            <div className="space-y-3">
              <RecordGroup title={t('documents.linked_rfis', { defaultValue: 'RFIs' })} rows={links.rfis} />
              <RecordGroup title={t('documents.linked_ncrs', { defaultValue: 'NCRs' })} rows={links.ncrs} />
              <RecordGroup
                title={t('documents.linked_change_orders', { defaultValue: 'Change orders' })}
                rows={links.change_orders}
              />
            </div>
          ) : null}
        </div>
      </div>
    </WideModal>
  );
}
