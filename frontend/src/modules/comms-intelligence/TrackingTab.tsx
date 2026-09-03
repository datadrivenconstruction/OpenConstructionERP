import { useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '@/stores/useToastStore';

import './ci.css';
import { type Kind, type ProjectTracking, type TrackState, fetchProjectTracking } from './registers-api';
import { EmailReader } from './EmailReader';
import { useMenu } from './ContextMenu';
import { attachReplyFlow } from './RegisterWorkspace';

/**
 * Email tracking — who owes an answer, and how long they have owed it.
 *
 * The send log could always answer "how many did I draft", which is the
 * least useful of the three questions. This screen answers the other two:
 * who has come back, and who has gone quiet. Silence is the one that
 * costs money and the one nothing surfaced before — a supplier who never
 * replies looks identical to one you never asked until the package is
 * late.
 *
 * Longest silence first, because that is the order you work the phone in.
 */

const STATE_LABEL: Record<TrackState, string> = {
  not_asked: 'not asked',
  waiting: 'waiting',
  chase: 'chase them',
  overdue: 'overdue',
  replied: 'replied',
  quoted: 'quoted',
};

export function TrackingTab({
  projectId,
  onOpenItem,
  onChase,
}: {
  projectId: string;
  /** Jump to the register and open this item. The KIND comes too:
   *  the item is filed under one of six register tabs and expanding it
   *  under the wrong one shows an empty list. */
  onOpenItem?: (itemId: string, kind: Kind) => void;
  /** Open the item so it can be chased. */
  onChase?: (itemId: string, kind: Kind) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const menu = useMenu();
  // Reading the reply from here rather than making somebody find the
  // item, open it, scroll to the thread and click through. The row
  // already carries the correspondence id - it simply went unused.
  const [reading, setReading] = useState<{ itemId: string; correspondenceId: string } | null>(null);
  const q = useQuery({
    queryKey: ['register-tracking', projectId],
    queryFn: () => fetchProjectTracking(projectId),
    enabled: !!projectId,
  });

  // Right-click a row: everything the two buttons do, plus filing a reply
  // by hand and copying the address you are about to ring.
  const rowMenu = (e: ReactMouseEvent, r: ProjectTracking['outstanding'][number]) =>
    menu.openFromEvent(
      e,
      [
        {
          label: t('ci.menu_attach_reply', { defaultValue: '📥 Attach a reply / response' }),
          onClick: () =>
            void attachReplyFlow({ id: r.item_id, reference: r.reference }, { t, addToast, queryClient, projectId }),
        },
        {
          label:
            r.state === 'replied' || r.state === 'quoted'
              ? t('ci.trk_menu_email', { defaultValue: '📧 Draft an email to them' })
              : t('ci.trk_menu_chase', { defaultValue: '📧 Draft a chase' }),
          note: r.chases > 0 ? t('ci.trk_menu_chased', { defaultValue: 'chased {{n}}×', n: r.chases }) : undefined,
          onClick: () => onChase?.(r.item_id, r.kind),
        },
        r.correspondence_id
          ? {
              label: t('ci.cm_open_their_reply', { defaultValue: 'Open their reply' }),
              note: r.reply_count && r.reply_count > 1 ? `${r.reply_count}` : undefined,
              onClick: () => setReading({ itemId: r.item_id, correspondenceId: r.correspondence_id as string }),
            }
          : null,
        {
          label: t('ci.trk_menu_thread', { defaultValue: 'Open the thread on {{r}}', r: r.reference }),
          onClick: () => onOpenItem?.(r.item_id, r.kind),
        },
        null,
        r.email
          ? {
              label: t('ci.menu_copy_email', { defaultValue: 'Copy email address' }),
              note: r.email,
              onClick: () => void navigator.clipboard.writeText(r.email),
            }
          : null,
        {
          label: t('ci.menu_copy', { defaultValue: 'Copy the reference' }),
          note: r.reference,
          onClick: () => void navigator.clipboard.writeText(r.reference),
        },
      ],
      { head: `${r.reference} · ${r.name}` },
    );

  if (q.isLoading) {
    return <div className="ci-empty">{t('common.loading', { defaultValue: 'Loading…' })}</div>;
  }
  if (q.error) {
    return <div className="ci-empty">{(q.error as Error).message}</div>;
  }

  const data = q.data;
  const rows = data?.outstanding ?? [];
  const totals = data?.totals;

  return (
    <div className="ci trk">
      <div className="tiles">
        <div className="tile">
          <b>{totals?.emails_sent ?? 0}</b>
          <span>{t('ci.trk_sent', { defaultValue: 'emails sent' })}</span>
        </div>
        <div className="tile">
          <b>{totals?.awaiting_reply ?? 0}</b>
          <span>{t('ci.trk_waiting', { defaultValue: 'awaiting a reply' })}</span>
        </div>
        <div className={`tile ${(totals?.to_chase ?? 0) > 0 ? 'bad' : 'good'}`}>
          <b>{totals?.to_chase ?? 0}</b>
          <span>{t('ci.trk_chase', { defaultValue: 'need chasing' })}</span>
        </div>
        <div className={`tile ${(totals?.overdue ?? 0) > 0 ? 'bad' : 'good'}`}>
          <b>{totals?.overdue ?? 0}</b>
          <span>{t('ci.trk_overdue', { defaultValue: 'overdue' })}</span>
        </div>
      </div>

      <div className="ci-card">
        <h3>{t('ci.trk_title', { defaultValue: '■ WHO OWES YOU AN ANSWER' })}</h3>
        {rows.length === 0 ? (
          <p className="ci-empty">
            {t('ci.trk_none', {
              defaultValue: 'Nobody is outstanding — everyone asked has come back.',
            })}
          </p>
        ) : (
          <div className="trk-scroll">
            <table className="trk-tbl">
              <thead>
                <tr>
                  <th>{t('ci.trk_item', { defaultValue: 'Item' })}</th>
                  <th>{t('ci.trk_who', { defaultValue: 'Who' })}</th>
                  <th>{t('ci.trk_state', { defaultValue: 'State' })}</th>
                  <th className="n">{t('ci.trk_days', { defaultValue: 'Days' })}</th>
                  <th className="n">{t('ci.trk_asks', { defaultValue: 'Asks' })}</th>
                  <th>{t('ci.trk_last', { defaultValue: 'Last sent' })}</th>
                  <th>{t('ci.trk_do', { defaultValue: 'Do' })}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={`${r.item_id}:${r.contact_id ?? r.name}`}
                    onContextMenu={(e) => rowMenu(e, r)}
                    title={t('ci.rightclick', { defaultValue: 'right-click for actions' })}
                  >
                    <td>
                      {/* The reference was a dead end: every row named an
                          item you then had to go and find by hand. */}
                      <button
                        type="button"
                        className="linkish"
                        onClick={() => onOpenItem?.(r.item_id, r.kind)}
                        title={t('ci.trk_open_item', { defaultValue: 'Open this item in the register' })}
                      >
                        <b className="ref">{r.reference}</b>
                      </button>{' '}
                      <span className="ttl">{r.title}</span>
                      {r.due_date && (
                        <span className="em">
                          {t('ci.trk_due', { defaultValue: 'due {{d}}', d: r.due_date })}
                        </span>
                      )}
                    </td>
                    <td>
                      <b>{r.name}</b>
                      {r.email && <span className="em">{r.email}</span>}
                    </td>
                    <td>
                      <span className={`st ${r.state}`}>{STATE_LABEL[r.state]}</span>
                    </td>
                    <td className="n">{r.days_waiting ?? '—'}</td>
                    <td className="n">
                      {r.sent_count}
                      {r.chases > 0 && <span className="ch"> +{r.chases}</span>}
                    </td>
                    <td className="dt">{(r.last_sent_at ?? '').replace('T', ' ').slice(0, 16) || '—'}</td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        {r.correspondence_id && (
                          <button
                            type="button"
                            className="b mini"
                            onClick={() =>
                              setReading({
                                itemId: r.item_id,
                                correspondenceId: r.correspondence_id as string,
                              })
                            }
                            title={r.reply_subject ?? undefined}
                          >
                            {t('ci.trk_read', { defaultValue: 'read' })}
                            {(r.reply_count ?? 0) > 1 && ` (${r.reply_count})`}
                          </button>
                        )}
                        {r.state !== 'replied' && r.state !== 'quoted' && (
                          <button
                            type="button"
                            className="b mini"
                            onClick={() => onChase?.(r.item_id, r.kind)}
                            title={t('ci.trk_chase_hint', {
                              defaultValue: 'Open the email for this item to chase them',
                            })}
                          >
                            {t('ci.trk_chase_do', { defaultValue: 'chase' })}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reading && (
          <EmailReader
            itemId={reading.itemId}
            correspondenceId={reading.correspondenceId}
            onClose={() => setReading(null)}
          />
        )}
        {menu.element}
        <p className="foot">
          {t('ci.trk_foot', {
            defaultValue:
              'Counted from the send log and the replies filed against each item. "Asks" is how many times they were written to; +n is chasers.',
          })}
        </p>
      </div>
    </div>
  );
}
