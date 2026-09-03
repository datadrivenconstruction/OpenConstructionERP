// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The printable request sheet - what goes out to the workshop floor on
 * paper, and what "Save as PDF" produces.
 *
 * It is a REAL component in the live tree, portalled to `<body>` and
 * hidden on screen, printed by a `@media print` block that hides
 * everything else (see `wr.css`). The tempting alternative - open a
 * window and write a re-serialised copy of the HTML into it - loses the
 * stylesheet, loses the fonts, is blocked by every popup blocker, and,
 * worst of all, silently drifts from the screen it claims to reproduce
 * because it is a second rendering of the same data. This one cannot
 * drift: it renders the same `WorkRequest` object the drawer does.
 *
 * The sheet is deliberately plain: black on white, one column of blocks,
 * a signature strip at the foot. No dark-mode tokens reach it - a panel
 * that is near-black on screen prints as a solid black rectangle, or (in
 * most browsers' default) as nothing at all, taking its white text with
 * it.
 */

import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import type { Department, UserRow, WorkRequest } from './api';
import {
  PRIORITY_LABEL,
  STATUS_LABEL,
  atCompletion,
  checklistOf,
  checklistProgress,
  deptOf,
  fieldSpecsOf,
  fmtDay,
  fmtDeviation,
  fmtHours,
  fmtMoney,
  fmtWhen,
  isLate,
  lateWords,
  moneyNumber,
  nameOfUser,
  personNames,
  stageOf,
  typeLabelsOf,
} from './lib';
import './wr.css';

/** One `key: value` line of the two-column table. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="wrp-row">
      <span className="k">{label}</span>
      <span className="v">{children}</span>
    </div>
  );
}

function Block({ title, children, wide = false }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <section className={wide ? 'wrp-block wide' : 'wrp-block'}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** A typed field's value as one printable line. */
function printValue(value: unknown, type: string): string {
  if (value === null || value === undefined || value === '') return '—';
  if (type === 'bool') return value ? 'Yes' : 'No';
  if (type === 'date') return fmtDay(String(value));
  return String(value);
}

export function RequestPrintSheet({
  req,
  departments,
  users = [],
  onDone,
  /**
   * Print on mount. False in a test (and in a story), where the sheet is
   * rendered to be READ rather than sent to a printer - jsdom has no
   * `window.print` at all, and a component that assumes one takes every
   * test that renders it down.
   */
  autoPrint = true,
}: {
  req: WorkRequest;
  departments: Department[];
  /** To turn a checklist tick's user ID into a person - see `nameOfUser`. */
  users?: UserRow[];
  onDone: () => void;
  autoPrint?: boolean;
}) {
  const { t } = useTranslation();
  const dept = deptOf(departments, req.department);
  const doneRef = useRef(false);

  useEffect(() => {
    const finish = () => {
      // `afterprint` fires once per print in most browsers and twice in a
      // couple of them; the guard keeps the caller's unmount idempotent.
      if (doneRef.current) return;
      doneRef.current = true;
      onDone();
    };
    window.addEventListener('afterprint', finish);
    let raf = 0;
    if (autoPrint && typeof window.print === 'function') {
      // One frame so the portal is laid out before the print dialog
      // snapshots the page; printing from inside the commit prints the
      // page as it was a moment ago, which is to say without this sheet.
      raf = window.requestAnimationFrame(() => {
        try {
          window.print();
        } catch {
          /* a browser that refuses to print leaves the sheet on screen */
        }
        // Safari and Firefox return from `print()` synchronously and fire
        // `afterprint`; Chrome fires it too. A browser that fires neither
        // would strand the sheet, so the return is treated as done as
        // well - the listener above simply wins whichever arrives first.
        finish();
      });
    }
    return () => {
      window.removeEventListener('afterprint', finish);
      if (raf) window.cancelAnimationFrame(raf);
    };
    // Mount-only: re-running would print again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stage = stageOf(dept, req.stage);
  const specs = fieldSpecsOf(req, dept);
  const ac = atCompletion(req);
  const dev = req.deviation_hours ?? (ac !== null && req.quoted_hours !== null ? ac - req.quoted_hours : null);
  const rate = moneyNumber(dept?.hourly_rate);
  const cost = moneyNumber(req.cost_at_completion) ?? (rate !== null && ac !== null ? ac * rate : null);
  const items = checklistOf(req);
  const progress = checklistProgress(req);
  const related = [
    ...req.depends_on.map((r) => ({ ...r, how: t('wr.depends_on', { defaultValue: 'Depends on' }) })),
    ...req.blocks.map((r) => ({ ...r, how: t('wr.blocks', { defaultValue: 'Blocks' }) })),
    ...req.children.map((r) => ({ ...r, how: t('wr.children', { defaultValue: 'Handed off as' }) })),
  ];

  const sheet = (
    <div className="wr-print-root" data-testid="wr-print-sheet" role="document" aria-label={t('wr.print_sheet', { defaultValue: 'Request sheet' })}>
      <article className="wrp">
        {/* ── Header ─────────────────────────────────────────────────
            A `div`, not a `<header>`: the app's own global print
            stylesheet hides `aside, nav, header, button` outright, which
            would take the reference, the title and the job off the top of
            every printed sheet. The block below in wr.css defends against
            that too, but not relying on it is cheaper than debugging it. */}
        <div className="wrp-head">
          <div className="wrp-head-main">
            <div className="ref">{req.reference}</div>
            <h1>{req.title}</h1>
            <div className="sub">
              <b>{req.project_code}</b> {req.project_name}
              {req.client_name ? ` · ${req.client_name}` : ''}
            </div>
          </div>
          <div className="wrp-head-side">
            <Row label={t('wr.department', { defaultValue: 'Department' })}>{dept?.name ?? req.department}</Row>
            <Row label={t('wr.col_status', { defaultValue: 'Status' })}>
              {t(`wr.status.${req.status}`, { defaultValue: STATUS_LABEL[req.status] ?? req.status })}
              {stage ? ` · ${stage.name}` : req.stage ? ` · ${req.stage}` : ''}
            </Row>
            <Row label={t('wr.request_type', { defaultValue: 'Request type' })}>{typeLabelsOf(req, dept).join(' · ') || '—'}</Row>
            <Row label={t('wr.raised', { defaultValue: 'Raised' })}>
              {fmtWhen(req.created_at)} · {req.raised_by_name}
            </Row>
            {isLate(req) && (
              <Row label={t('wr.late_lbl', { defaultValue: 'Late' })}>
                <b>{lateWords(req)}</b>
                {req.target_date ? ` (${t('wr.target_date', { defaultValue: 'target' })} ${fmtDay(req.target_date)})` : ''}
              </Row>
            )}
          </div>
        </div>

        {/* ── The typed fields, two to a row ─────────────────────── */}
        {specs.length > 0 && (
          <Block title={t('wr.sec_details', { defaultValue: 'Details' })}>
            <div className="wrp-grid">
              {specs.map((f) => (
                <Row key={f.key} label={f.label}>
                  {printValue(req.fields?.[f.key], f.type)}
                </Row>
              ))}
            </div>
          </Block>
        )}

        {/* ── Scope ──────────────────────────────────────────────── */}
        <Block title={t('wr.scope', { defaultValue: 'Scope / description' })} wide>
          <p className="wrp-prose">{req.description?.trim() || t('wr.no_description', { defaultValue: 'No description was given.' })}</p>
        </Block>

        {/* ── People and dates ───────────────────────────────────── */}
        <Block title={t('wr.sec_people_dates', { defaultValue: 'People & dates' })}>
          <div className="wrp-grid">
            <Row label={t('wr.raised_by', { defaultValue: 'Raised by' })}>{req.raised_by_name || '—'}</Row>
            <Row label={t('wr.responsible', { defaultValue: 'Responsible' })}>{req.responsible?.name ?? '—'}</Row>
            <Row label={t('wr.assignees', { defaultValue: 'Assignees' })}>{personNames(req.assignees) || '—'}</Row>
            <Row label={t('wr.priority_lbl', { defaultValue: 'Priority' })}>{t(`wr.priority.${req.priority}`, { defaultValue: PRIORITY_LABEL[req.priority] ?? req.priority })}</Row>
            <Row label={t('wr.info_by', { defaultValue: 'Info required by' })}>{fmtDay(req.info_required_by)}</Row>
            <Row label={t('wr.due', { defaultValue: 'Due' })}>{fmtDay(req.due_date)}</Row>
            <Row label={t('wr.sched_start', { defaultValue: 'Scheduled start' })}>{fmtDay(req.scheduled_start)}</Row>
            <Row label={t('wr.sched_end', { defaultValue: 'Scheduled end' })}>{fmtDay(req.scheduled_end)}</Row>
            <Row label={t('wr.delivered', { defaultValue: 'Delivered' })}>{fmtDay(req.delivered_at)}</Row>
            <Row label={t('wr.tested', { defaultValue: 'Tested' })}>{fmtDay(req.tested_at)}</Row>
          </div>
        </Block>

        {/* ── Hours and cost ─────────────────────────────────────── */}
        <Block title={t('wr.sec_hours', { defaultValue: 'Hours & cost' })}>
          <div className="wrp-grid">
            <Row label={t('wr.quoted', { defaultValue: 'Quoted' })}>{fmtHours(req.quoted_hours)}</Row>
            <Row label={t('wr.logged', { defaultValue: 'Logged' })}>{fmtHours(req.hours_logged)}</Row>
            <Row label={t('wr.to_complete', { defaultValue: 'To complete' })}>{fmtHours(req.hours_to_complete)}</Row>
            <Row label={t('wr.at_completion', { defaultValue: 'At completion' })}>{fmtHours(ac)}</Row>
            <Row label={t('wr.deviation', { defaultValue: 'Deviation' })}>{fmtDeviation(dev)}</Row>
            {/* Only when a rate exists: an invented cost on a printed
                sheet is a number somebody will quote back at you. */}
            {cost !== null && (
              <Row label={t('wr.cost_at_completion', { defaultValue: 'Cost at completion' })}>
                {fmtMoney(cost)}
                {rate !== null ? ` (${t('wr.rate_hint', { defaultValue: '@ {{r}}/h', r: fmtMoney(rate) })})` : ''}
              </Row>
            )}
          </div>
        </Block>

        {/* ── Checklist, with boxes to tick in ink ───────────────── */}
        {items.length > 0 && (
          <Block title={t('wr.sec_checklist', { defaultValue: 'Checklist' })} wide>
            <p className="wrp-note">{t('wr.checklist_progress', { defaultValue: '{{done}} of {{total}}', done: progress.done, total: progress.total })}</p>
            <ul className="wrp-check">
              {items.map((i) => (
                <li key={i.key}>
                  <span className="box" aria-hidden>
                    {i.done ? '×' : ''}
                  </span>
                  <span className="lbl">
                    {i.label}
                    {i.required && <b className="req"> *</b>}
                  </span>
                  {/* `by` is a user ID on the wire. A printed sheet that
                      says "e58c94e2-3258-…" beside a signed-off line is
                      worse than one that says nothing, so an id this
                      sheet cannot place shows only the date. */}
                  <span className="by">{i.done ? [nameOfUser(users, i.by), i.at ? fmtDay(i.at) : null].filter(Boolean).join(' · ') : ''}</span>
                </li>
              ))}
            </ul>
            <p className="wrp-note">{t('wr.checklist_required_note', { defaultValue: '* must be signed off before the request can be closed.' })}</p>
          </Block>
        )}

        {/* ── Dependencies and links ─────────────────────────────── */}
        {(related.length > 0 || req.links.length > 0 || req.attachments.length > 0 || req.parent_reference) && (
          <Block title={t('wr.sec_deps_links', { defaultValue: 'Dependencies & links' })} wide>
            <ul className="wrp-list">
              {req.parent_reference && (
                <li>
                  <b>{t('wr.parent', { defaultValue: 'Parent' })}:</b> {req.parent_reference}
                </li>
              )}
              {related.map((r) => (
                <li key={`${r.how}-${r.id}`}>
                  <b>{r.how}:</b> {r.reference} {r.title}
                </li>
              ))}
              {req.links.map((l, i) => (
                <li key={`${l.url}-${i}`}>
                  <b>{l.label || t('wr.link_url', { defaultValue: 'URL' })}:</b> {l.url}
                </li>
              ))}
              {req.attachments.map((a) => (
                <li key={a.filename}>
                  <b>{t('wr.attachment', { defaultValue: 'File' })}:</b> {a.filename}
                </li>
              ))}
            </ul>
          </Block>
        )}

        {/* ── The signature strip ────────────────────────────────── */}
        <div className="wrp-sign">
          <div className="wrp-signs">
            <div className="s">
              <span className="line" />
              <span className="cap">{t('wr.sign_completed', { defaultValue: 'Completed by' })}</span>
            </div>
            <div className="s">
              <span className="line" />
              <span className="cap">{t('wr.sign_checked', { defaultValue: 'Checked by' })}</span>
            </div>
            <div className="s narrow">
              <span className="line" />
              <span className="cap">{t('wr.date', { defaultValue: 'Date' })}</span>
            </div>
          </div>
          <p className="wrp-note">
            {t('wr.print_footer', {
              defaultValue: '{{ref}} · printed {{when}} · this sheet is a snapshot; the live request is the record.',
              ref: req.reference,
              when: fmtWhen(new Date().toISOString()),
            })}
          </p>
        </div>
      </article>
    </div>
  );

  return createPortal(sheet, document.body);
}
