import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { ContactRow, RegisterItemRow } from './registers-api';

/**
 * 'These already went out' - tick the ones that did.
 *
 * The old flow asked for a name and a date as two typed prompts, which
 * meant retyping suppliers the item already names and typing today's date
 * by hand, once per supplier. An RFQ almost always issues to a list, so
 * the list is what the dialog should show: every recipient on the item,
 * a box to tick, and the date already filled in.
 */

export interface LogSentRow {
  contact_id: string | null;
  contact_name: string;
  email: string;
  /** Already logged as sent - shown ticked and disabled, never double-counted. */
  already: boolean;
  last_sent?: string | null;
}

function todayISO(): string {
  // The record wants the DAY it went out; a local date is what a person
  // means by 'yesterday', so this is deliberately not UTC.
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function LogSentDialog({
  item,
  recipients,
  onCancel,
  onConfirm,
}: {
  item: RegisterItemRow;
  recipients: LogSentRow[];
  onCancel: () => void;
  onConfirm: (
    entries: {
      contact_id: string | null;
      contact_name: string;
      sent_on: string;
    }[],
  ) => void;
}) {
  const { t } = useTranslation();
  const [when, setWhen] = useState(todayISO());
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [extra, setExtra] = useState('');

  const keyOf = (r: LogSentRow, i: number) =>
    r.contact_id ?? `n:${r.contact_name}:${i}`;

  // Default: everyone not already logged is ticked. The common case is
  // 'I sent the lot', so that should be zero clicks.
  useEffect(() => {
    const next: Record<string, boolean> = {};
    recipients.forEach((r, i) => {
      next[keyOf(r, i)] = !r.already;
    });
    setTicked(next);
  }, [recipients]);

  const chosen = useMemo(
    () => recipients.filter((r, i) => ticked[keyOf(r, i)] && !r.already),
    [recipients, ticked],
  );
  const extraNames = extra
    .split(/[;,\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
  const total = chosen.length + extraNames.length;

  const dateLooksOdd = when > todayISO();

  return (
    // Same wrapper as qAsk: the module's scrim does the positioning, so
    // this dialog sits exactly where every other one in the page does.
    <div className='ci' style={{ position: 'fixed', inset: 0, zIndex: 82 }}>
      <div className='ci-scrim' onClick={onCancel}>
        <div
          className='qbox qlog'
          role='dialog'
          aria-modal='true'
          aria-label='Log emails already sent'
          onClick={(e) => e.stopPropagation()}
        >
          <header>
            <b>
              {t('ci.log_sent_title', {
                defaultValue: 'Log emails that already went out',
              })}
            </b>
            <span className='ref'>{item.reference}</span>
            <button
              type='button'
              className='x'
              onClick={onCancel}
              aria-label='Close'
            >
              ✕
            </button>
          </header>

          <div className='when'>
            <label htmlFor='logsent-date'>
              {t('ci.log_sent_when', { defaultValue: 'Date they went out' })}
            </label>
            <input
              id='logsent-date'
              type='date'
              value={when}
              max={todayISO()}
              onChange={(e) => setWhen(e.target.value)}
            />
            {dateLooksOdd && (
              <span className='warn'>
                {t('ci.log_sent_future', {
                  defaultValue: 'That is in the future',
                })}
              </span>
            )}
          </div>

          <div className='rows'>
            {recipients.length === 0 && (
              <p className='none'>
                {t('ci.log_sent_nobody', {
                  defaultValue:
                    'This item names nobody yet - add the recipient below.',
                })}
              </p>
            )}
            {recipients.map((r, i) => {
              const key = keyOf(r, i);
              const on = r.already || !!ticked[key];
              return (
                <label key={key} className={`row${r.already ? ' done' : ''}`}>
                  <input
                    type='checkbox'
                    checked={on}
                    disabled={r.already}
                    onChange={(e) =>
                      setTicked((p) => ({ ...p, [key]: e.target.checked }))
                    }
                  />
                  <span className='tick' aria-hidden='true' />
                  <span className='who'>
                    <b>{r.contact_name}</b>
                    {r.email && <span className='em'>{r.email}</span>}
                  </span>
                  {r.already && (
                    <span className='already'>
                      {t('ci.log_sent_already', {
                        defaultValue: 'already logged',
                      })}
                      {r.last_sent ? ` · ${r.last_sent.slice(0, 10)}` : ''}
                    </span>
                  )}
                </label>
              );
            })}
          </div>

          <div className='anyone'>
            <label htmlFor='logsent-extra'>
              {t('ci.log_sent_extra', {
                defaultValue: 'Anyone else (comma separated)',
              })}
            </label>
            <input
              id='logsent-extra'
              type='text'
              value={extra}
              placeholder='Acme Supplies, Northbank Electrical'
              onChange={(e) => setExtra(e.target.value)}
            />
          </div>

          <footer>
            <span className='count'>
              {total === 0
                ? t('ci.log_sent_none', { defaultValue: 'Nothing ticked' })
                : t('ci.log_sent_count', {
                    defaultValue: '{{count}} to log',
                    count: total,
                  })}
            </span>
            <button type='button' className='b' onClick={onCancel}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
            <button
              type='button'
              className='b pri'
              disabled={total === 0}
              onClick={() =>
                onConfirm([
                  ...chosen.map((r) => ({
                    contact_id: r.contact_id,
                    contact_name: r.contact_name,
                    sent_on: when,
                  })),
                  ...extraNames.map((name) => ({
                    contact_id: null,
                    contact_name: name,
                    sent_on: when,
                  })),
                ])
              }
            >
              {t('ci.log_sent_go', { defaultValue: 'Log on the record' })}
            </button>
          </footer>
        </div>
      </div>
    </div>
  );
}

/** Build the dialog's rows from the item and its looked-up contacts. */
export function logSentRows(
  item: RegisterItemRow,
  contacts: ContactRow[],
): LogSentRow[] {
  const log =
    ((item.fields as Record<string, unknown>)['_send_log'] as
      | { contact_id?: string | null; contact_name?: string; at?: string }[]
      | undefined) ?? [];
  const sentIds = new Set(
    log.map((l) => String(l.contact_id ?? '')).filter(Boolean),
  );
  const lastFor = (id: string) =>
    log
      .filter((l) => String(l.contact_id ?? '') === id)
      .map((l) => l.at ?? '')
      .sort()
      .pop() ?? null;

  const byId = new Map(contacts.map((c) => [c.id, c]));
  const rows: LogSentRow[] = (item.recipient_contact_ids ?? []).map((id) => {
    const c = byId.get(id);
    const name =
      c?.company_name ||
      [c?.first_name, c?.last_name].filter(Boolean).join(' ') ||
      c?.primary_email ||
      id;
    return {
      contact_id: id,
      contact_name: name,
      email: c?.primary_email ?? '',
      already: sentIds.has(id),
      last_sent: lastFor(id),
    };
  });

  // Someone written to by hand before is worth offering again - it is
  // usually the same person on the next issue.
  for (const entry of log) {
    if (entry.contact_id) continue;
    const name = String(entry.contact_name ?? '').trim();
    if (name && !rows.some((r) => r.contact_name === name)) {
      rows.push({
        contact_id: null,
        contact_name: name,
        email: '',
        already: true,
        last_sent: entry.at ?? null,
      });
    }
  }
  return rows;
}
