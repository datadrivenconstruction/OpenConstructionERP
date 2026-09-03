// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The record picker — "Link to an existing record".
 *
 * A reference on its own tells you nothing, so a link is chosen from a
 * list that shows what each record actually is: kind, title, job, when
 * it was raised, where its workflow stands and who it is with — with a
 * preview of the chosen one beside the list before you commit.
 *
 * Same shape as the Team Standup board's picker: search box, kind chips,
 * "This job only" ↔ "All jobs", the list, the preview, one confirm.
 * Escape closes, Enter confirms, a double-click confirms.
 */

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '@/stores/useToastStore';
import { fmtDate as fmtDateShared } from '@/shared/lib/formatters';
import './ci.css';
import {
  type Kind,
  type KindSpec,
  type RegisterItemRow,
  addItemLink,
  fetchItems,
  fetchPortfolio,
  fetchSpec,
} from './registers-api';

export const KIND_ORDER: Kind[] = ['rfi', 'rfq', 'order', 'variation', 'delay', 'toolbox'];

export const KIND_LABEL: Record<Kind, string> = {
  rfi: 'RFI',
  rfq: 'RFQ',
  order: 'Order',
  variation: 'Variation',
  delay: 'Delay',
  toolbox: 'Toolbox',
};

/** One colour per kind, the standup's link palette, so a chip on the
 *  board and a tag here read as the same thing. */
export const KIND_COLOR: Record<Kind, string> = {
  rfi: '#6136ad',
  rfq: '#2f42a8',
  order: '#1361c9',
  variation: '#a4470c',
  delay: '#0a6f66',
  toolbox: '#4f6a10',
};

/** Tinted tag style: soft wash, coloured text, faint edge. */
export function kindTint(kind: Kind): CSSProperties {
  const c = KIND_COLOR[kind] ?? '#55616e';
  return {
    color: c,
    background: `color-mix(in srgb, ${c} 12%, transparent)`,
    borderColor: `color-mix(in srgb, ${c} 30%, transparent)`,
  };
}

/** The job number a reference carries: REG-RFQ-25406-0001 → 25406. */
export function jobOf(reference: string, fallback = ''): string {
  const m = reference.match(/-(\d{3,})-\d+$/);
  return m?.[1] ?? fallback;
}

/** The ERP's own date rendering ("02 Sep 2026"), so the picker reads like
 *  the hub widget beside it rather than a locale of its own. */
const fmtDate = (iso: string | null | undefined): string => (iso ? fmtDateShared(iso) : '—');

type PickRow = RegisterItemRow & { job: string; jobName: string };

const withWhom = (r: RegisterItemRow): string => r.ball_in_court_name || r.responsible || '';

/** An item raised without a title carries its reference as one. */
const titleOf = (r: RegisterItemRow): string => (r.title && r.title !== r.reference ? r.title : '');

export function RecordPicker({
  item,
  projectId,
  projectName,
  exclude,
  onClose,
  onLinked,
}: {
  /** The item being linked FROM. */
  item: RegisterItemRow;
  projectId: string;
  projectName?: string | null;
  /** References already linked - offered again they would only fail. */
  exclude?: string[];
  onClose: () => void;
  onLinked?: (reference: string) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [q, setQ] = useState('');
  const [kind, setKind] = useState<Kind | ''>('');
  const [scope, setScope] = useState<'job' | 'all'>('job');
  const [sel, setSel] = useState<PickRow | null>(null);
  const [busy, setBusy] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const thisJob = jobOf(item.reference, projectName || '');

  const spec = useQuery({ queryKey: ['registers-spec'], queryFn: fetchSpec, staleTime: 300_000 });
  const local = useQuery({
    queryKey: ['registers', projectId, 'picker'],
    queryFn: () => fetchItems(projectId),
    enabled: !!projectId,
  });
  // The other jobs, only when asked for: every project's register is a
  // round trip each, capped at 25 - the portfolio is ordered by need.
  const others = useQuery({
    queryKey: ['registers-picker-all', projectId],
    queryFn: async () => {
      const jobs = (await fetchPortfolio()).filter((p) => p.project_id !== projectId).slice(0, 25);
      const lists = await Promise.all(
        jobs.map(async (p) => {
          try {
            const rows = await fetchItems(p.project_id);
            return rows.map((r) => ({ ...r, jobName: p.project_name }));
          } catch {
            return [];
          }
        }),
      );
      return lists.flat();
    },
    enabled: scope === 'all',
    staleTime: 60_000,
  });

  useEffect(() => {
    const id = window.setTimeout(() => searchRef.current?.focus(), 40);
    return () => window.clearTimeout(id);
  }, []);

  const rows = useMemo<PickRow[]>(() => {
    const skip = new Set(exclude ?? []);
    const seen = new Set<string>();
    const base: (RegisterItemRow & { jobName?: string })[] = [
      ...(local.data ?? []).map((r) => ({ ...r, jobName: projectName || '' })),
      ...(scope === 'all' ? others.data ?? [] : []),
    ];
    const needle = q.trim().toLowerCase();
    const out: PickRow[] = [];
    for (const r of base) {
      if (r.id === item.id || seen.has(r.id) || skip.has(r.reference)) continue;
      seen.add(r.id);
      if (kind && r.kind !== kind) continue;
      const row: PickRow = { ...r, jobName: r.jobName ?? '', job: jobOf(r.reference, r.jobName ?? '') };
      if (needle) {
        const hay = [
          r.reference,
          r.title,
          withWhom(r),
          r.status,
          r.current_step ?? '',
          row.job,
          row.jobName,
        ]
          .join(' ')
          .toLowerCase();
        if (!hay.includes(needle)) continue;
      }
      out.push(row);
    }
    // Newest first - the thing you are linking to is usually recent.
    return out.sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')));
  }, [local.data, others.data, scope, q, kind, exclude, item.id, projectName]);

  // A selection that the filter has since hidden is no selection.
  useEffect(() => {
    if (sel && !rows.some((r) => r.id === sel.id)) setSel(null);
  }, [rows, sel]);

  const confirmWith = async (row: PickRow | null) => {
    if (!row || busy) return;
    setBusy(true);
    try {
      await addItemLink(item.id, 'item', row.reference);
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
      addToast({
        type: 'success',
        title: t('ci.pick_linked', { defaultValue: 'Linked to {{r}}', r: row.reference }),
      });
      onLinked?.(row.reference);
      onClose();
    } catch (e) {
      addToast({ type: 'error', title: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  // Escape closes, Enter confirms, the arrows walk the list.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'Enter') {
        if (!sel) return;
        e.preventDefault();
        void confirmWith(sel);
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (rows.length === 0) return;
        e.preventDefault();
        const i = sel ? rows.findIndex((r) => r.id === sel.id) : -1;
        const next = e.key === 'ArrowDown' ? Math.min(rows.length - 1, i + 1) : Math.max(0, i - 1);
        setSel(rows[next] ?? null);
        document.getElementById(`ci-prow-${rows[next]?.id}`)?.scrollIntoView({ block: 'nearest' });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, rows, busy]);

  const specOf = (k: Kind): KindSpec | undefined => spec.data?.specs?.[k];
  const previewFields = (r: PickRow): [string, string][] => {
    const internal = new Set((specOf(r.kind)?.fields ?? []).filter((f) => f.internal).map((f) => f.label));
    return Object.entries(r.fields ?? {})
      .filter(([k, v]) => !k.startsWith('_') && !internal.has(k) && String(v ?? '').trim())
      .slice(0, 4) as [string, string][];
  };

  const loadingOthers = scope === 'all' && others.isLoading;
  const count =
    scope === 'job'
      ? t('ci.pick_count_job', {
          defaultValue_one: '{{count}} record on {{job}}',
          defaultValue_other: '{{count}} records on {{job}}',
          count: rows.length,
          job: thisJob || projectName || '',
        })
      : t('ci.pick_count_all', {
          defaultValue_one: '{{count}} record across all jobs',
          defaultValue_other: '{{count}} records across all jobs',
          count: rows.length,
        });

  // Portalled to the body: rendered inside a table row it would be
  // positioned against the row's transform, not the viewport.
  return createPortal(
    <div
      className="ci ci-pickscrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="pickmodal" role="dialog" aria-modal="true" aria-labelledby="ci-pick-title">
        <div className="pickhead">
          <h3 id="ci-pick-title">{t('ci.pick_title', { defaultValue: 'Link to an existing record' })}</h3>
          <span className="mref">
            {item.reference}
            {thisJob ? ` · ${thisJob}` : ''}
            {projectName ? ` · ${projectName}` : ''}
          </span>
          <button type="button" className="x" aria-label={t('common.close', { defaultValue: 'Close' })} onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="pickbar">
          <input
            ref={searchRef}
            className="grow"
            type="text"
            autoComplete="off"
            placeholder={t('ci.pick_search', {
              defaultValue: 'Search reference, title, party, status or current step…',
            })}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="chiprow" role="group" aria-label={t('ci.pick_kinds', { defaultValue: 'Record type' })}>
            <button type="button" className="pchip" aria-pressed={kind === ''} onClick={() => setKind('')}>
              {t('ci.pick_all_types', { defaultValue: 'All types' })}
            </button>
            {KIND_ORDER.map((k) => (
              <button
                key={k}
                type="button"
                className="pchip"
                aria-pressed={kind === k}
                style={kind === k ? kindTint(k) : undefined}
                onClick={() => setKind(kind === k ? '' : k)}
              >
                <span className="pdot" style={{ background: KIND_COLOR[k] }} aria-hidden />
                {KIND_LABEL[k]}
              </button>
            ))}
          </div>
          <span className="sep" aria-hidden />
          <button
            type="button"
            className={`b mini ${scope === 'job' ? 'on' : ''}`}
            aria-pressed={scope === 'job'}
            onClick={() => setScope((s) => (s === 'job' ? 'all' : 'job'))}
            title={t('ci.pick_scope_hint', { defaultValue: 'Click to switch between this job and every job' })}
          >
            {scope === 'job'
              ? t('ci.pick_this_job', { defaultValue: 'This job only' })
              : t('ci.pick_all_jobs', { defaultValue: 'All jobs' })}
          </button>
        </div>

        <div className="pickbody">
          <div className="picklist" role="listbox" aria-label={t('ci.pick_list', { defaultValue: 'Records' })}>
            {local.isLoading ? (
              <div className="pv-empty">{t('ci.pick_loading', { defaultValue: 'Loading the registers…' })}</div>
            ) : (
              <>
                {loadingOthers && (
                  <div className="pnote">{t('ci.pick_loading_others', { defaultValue: 'Loading the other jobs…' })}</div>
                )}
                {rows.length === 0 && !loadingOthers && (
                  <div className="pv-empty">
                    {t('ci.pick_none', {
                      defaultValue: 'Nothing matches. Try widening to all jobs, or raise a new record.',
                    })}
                  </div>
                )}
                {rows.map((r) => (
                  <div
                    key={r.id}
                    id={`ci-prow-${r.id}`}
                    className="prow"
                    role="option"
                    aria-selected={sel?.id === r.id}
                    onClick={() => setSel(r)}
                    onDoubleClick={() => {
                      setSel(r);
                      void confirmWith(r);
                    }}
                  >
                    <span className="ptag" style={kindTint(r.kind)}>
                      {KIND_LABEL[r.kind] ?? r.kind}
                    </span>
                    <span className="ptitle">{titleOf(r) || '—'}</span>
                    <span className="pdate" title={t('ci.pick_raised_lbl', { defaultValue: 'Raised' })}>
                      {fmtDate(r.created_at)}
                    </span>
                    <span className="pmeta">
                      <span className="ref">{r.reference}</span>
                      {' · '}
                      {r.job || r.jobName || '—'}
                    </span>
                    <span className="pmeta">
                      <span className="st">
                        {r.status === 'closed'
                          ? t('ci.pick_closed', { defaultValue: 'closed' })
                          : r.current_step || t('ci.pick_open', { defaultValue: 'open' })}
                      </span>
                      {withWhom(r) ? ` · ${t('ci.pick_with', { defaultValue: 'with {{w}}', w: withWhom(r) })}` : ''}
                    </span>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="pickview">
            {sel ? (
              <>
                <div className="pv-head">
                  <span className="ptag" style={kindTint(sel.kind)}>
                    {KIND_LABEL[sel.kind] ?? sel.kind}
                  </span>
                  <h4>{titleOf(sel) || '—'}</h4>
                  <span className="pv-ref">{sel.reference}</span>
                </div>
                <div className="pv-main">
                  <dl>
                    <dt>{t('ci.pick_job', { defaultValue: 'Job' })}</dt>
                    <dd>
                      {sel.job || '—'}
                      {sel.jobName ? ` · ${sel.jobName}` : ''}
                    </dd>
                    <dt>{t('ci.pick_raised_lbl', { defaultValue: 'Raised' })}</dt>
                    <dd>{fmtDate(sel.created_at)}</dd>
                    <dt>{t('ci.pick_status', { defaultValue: 'Status' })}</dt>
                    <dd>
                      {sel.status === 'closed'
                        ? t('ci.pick_closed', { defaultValue: 'closed' })
                        : t('ci.pick_open', { defaultValue: 'open' })}
                      {sel.is_overdue ? ` · ${t('ci.pick_overdue', { defaultValue: 'overdue' })}` : ''}
                      {sel.due_date
                        ? ` · ${t('ci.pick_due', { defaultValue: 'due {{d}}', d: fmtDate(sel.due_date) })}`
                        : ''}
                    </dd>
                    <dt>{t('ci.pick_step', { defaultValue: 'Current step' })}</dt>
                    <dd>{sel.current_step || '—'}</dd>
                    <dt>{t('ci.pick_with_lbl', { defaultValue: 'With' })}</dt>
                    <dd>
                      {sel.ball_in_court === 'them'
                        ? t('ci.with_them', { defaultValue: 'with them' })
                        : t('ci.with_us', { defaultValue: 'with us' })}
                      {withWhom(sel) ? ` · ${withWhom(sel)}` : ''}
                    </dd>
                    <dt>{t('ci.pick_steps', { defaultValue: 'Steps' })}</dt>
                    <dd>
                      {sel.steps_done} / {sel.steps_total}
                    </dd>
                  </dl>
                  {previewFields(sel).length > 0 && (
                    <div className="pv-body">
                      {previewFields(sel).map(([k, v]) => (
                        <div key={k}>
                          <span className="k">{k}</span>
                          <span className="val">{String(v).length > 400 ? `${String(v).slice(0, 400)}…` : String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="pv-empty">
                {t('ci.pick_hint', { defaultValue: 'Pick a record on the left to see what it is.' })}
              </div>
            )}
          </div>
        </div>

        <div className="pickfoot">
          <span className="count">{count}</span>
          <button type="button" className="b" onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button type="button" className="b pri" disabled={!sel || busy} onClick={() => void confirmWith(sel)}>
            {busy
              ? t('ci.pick_linking', { defaultValue: 'Linking…' })
              : t('ci.pick_confirm', { defaultValue: 'Link this record' })}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
