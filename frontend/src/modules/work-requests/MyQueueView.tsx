// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * My queue: the four lists the server keeps for the signed-in user, each
 * rendered with the same table as the List view.
 */

import { useTranslation } from 'react-i18next';
import type { Department, MyQueue, WorkRequest } from './api';
import type { RequestActions } from './actions';
import { RequestTable } from './RequestTable';
import type { Me } from './lib';

export function MyQueueView({
  queue,
  departments,
  me,
  actions,
  onOpen,
  selectedId,
}: {
  queue: MyQueue;
  departments: Department[];
  me: Me | null;
  actions: RequestActions;
  onOpen: (req: WorkRequest) => void;
  selectedId?: string | null;
}) {
  const { t } = useTranslation();
  const lists: { key: keyof MyQueue; title: string; empty: string }[] = [
    {
      key: 'needs_my_answer',
      title: t('wr.q_needs_answer', { defaultValue: 'Needs my answer' }),
      empty: t('wr.q_needs_answer_empty', { defaultValue: 'Nobody is waiting on an answer from you.' }),
    },
    { key: 'assigned', title: t('wr.q_assigned', { defaultValue: 'Assigned to me' }), empty: t('wr.q_assigned_empty', { defaultValue: 'Nothing is assigned to you.' }) },
    {
      key: 'responsible',
      title: t('wr.q_responsible', { defaultValue: "I'm responsible" }),
      empty: t('wr.q_responsible_empty', { defaultValue: 'You are not the responsible person on any open request.' }),
    },
    { key: 'raised', title: t('wr.q_raised', { defaultValue: 'Raised by me' }), empty: t('wr.q_raised_empty', { defaultValue: 'You have not raised a request yet.' }) },
  ];
  return (
    <div className="flex flex-col gap-5">
      {lists.map((l) => {
        const rows = queue[l.key] ?? [];
        return (
          <section key={l.key} aria-label={l.title}>
            <div className="mb-1.5 flex items-center gap-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-content-secondary">{l.title}</h3>
              <span className="wr-hint">{rows.length}</span>
            </div>
            <RequestTable rows={rows} departments={departments} me={me} actions={actions} onOpen={onOpen} selectedId={selectedId} emptyText={l.empty} showDepartment />
          </section>
        );
      })}
    </div>
  );
}
