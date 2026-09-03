// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * One request, in full: the header, the stage stepper, and the sections
 * (details, people, dates, hours & cost, dependencies, links, the
 * conversation, the activity). Used by the slide-over drawer and by the
 * full page at /work-requests/:id, so both show the same thing.
 *
 * Everything is edited in place: click a value, change it, Enter or blur
 * saves, Escape reverts. Every write goes through the module's client and
 * refreshes every list that shows the request.
 */

import { useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Paperclip, Pencil, Plus, Printer, Trash2, Upload } from 'lucide-react';
import clsx from 'clsx';
import { downloadWithAuth } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useMenu, type MenuItem } from '../comms-intelligence/ContextMenu';
import { qAsk, qConfirm } from '../comms-intelligence/qAsk';
import {
  PRIORITIES,
  answerInfo,
  assignRequest,
  attachmentUrl,
  deleteHours,
  fetchActivity,
  fetchComments,
  fetchHours,
  patchRequest,
  postComment,
  tickChecklist,
  uploadAttachment,
  type ChecklistItem,
  type Department,
  type PatchRequestBody,
  type Priority,
  type RelatedRequest,
  type RequestField,
  type WorkRequest,
} from './api';
import type { RequestActions } from './actions';
import { Avatar, Avatars, BallPill, HScroll, HoursBar, LatePill, PriorityGlyph, RefChip, Section, StatusPill } from './bits';
import { Checklist, ChecklistProgress } from './Checklist';
import { Feeds } from './Feeds';
import { WR, useCanManageWr, useInvalidateWr, useRequest, useRequests, useUsers, useWrMutation } from './hooks';
import { Picker, type PickAnchor } from './Pickers';
import {
  NEUTRAL,
  PRIORITY_LABEL,
  STATUS_COLOUR,
  atCompletion,
  ballWords,
  canEditChecklist,
  checklistOf,
  checklistProgress,
  copyText,
  deptOf,
  dueClause,
  errorText,
  fieldSpecsOf,
  fmtDay,
  fmtDeviation,
  fmtHours,
  fmtMoney,
  fmtWhen,
  isClosed,
  isModuleMissing,
  memberPool,
  moneyNumber,
  onDepartmentSide,
  outstandingRequired,
  resolveColour,
  shortUrl,
  stagesOf,
  tintStyle,
  typeKeysOf,
  typeLabelsOf,
  typesOf,
  unionDisciplines,
  type Me,
} from './lib';
import { ModuleMissing } from './ModuleMissing';
import { fmtFixed, fmtList } from '@/shared/lib/formatters';

export function RequestDetail({
  id,
  departments,
  me,
  actions,
  onOpenOther,
}: {
  id: string;
  departments: Department[];
  me: Me | null;
  actions: RequestActions;
  /** Open another request (a dependency, a child) in the same surface. */
  onOpenOther: (req: RelatedRequest | WorkRequest) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const invalidate = useInvalidateWr();
  const q = useRequest(id);
  const req = q.data;
  const dept = deptOf(departments, req?.department ?? '');
  const users = useUsers();
  const canManage = useCanManageWr();
  const menu = useMenu();
  const [picker, setPicker] = useState<{ at: PickAnchor; what: 'assignees' | 'responsible' | 'dependency' | 'mention' | 'types' } | null>(null);
  const [answer, setAnswer] = useState('');
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [inlineError, setInlineError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const commentRef = useRef<HTMLTextAreaElement>(null);
  const [comment, setComment] = useState('');
  const [mentions, setMentions] = useState<{ id: string; name: string }[]>([]);

  const hours = useQuery({ queryKey: [WR, 'hours', id], queryFn: () => fetchHours(id), enabled: !!req, retry: false });
  const comments = useQuery({ queryKey: [WR, 'comments', id], queryFn: () => fetchComments(id), enabled: !!req, retry: false });
  const activity = useQuery({ queryKey: [WR, 'activity', id], queryFn: () => fetchActivity(id), enabled: !!req, retry: false });
  const jobRequests = useRequests({ project_id: req?.project_id, include_closed: false }, !!req && picker?.what === 'dependency');

  const patchM = useWrMutation((patch: PatchRequestBody) => patchRequest(id, patch), {
    onError: (err) => setInlineError(errorText(err)),
    onSuccess: () => setInlineError(null),
  });
  const answerM = useWrMutation((a: string) => answerInfo(id, a), {
    onSuccess: () => {
      setAnswer('');
      addToast({ type: 'success', title: t('wr.answered', { defaultValue: 'Answer sent - the ball is back with the department.' }) });
    },
  });
  const commentM = useWrMutation(({ body, ids }: { body: string; ids: string[] }) => postComment(id, body, ids), {
    onSuccess: () => {
      setComment('');
      setMentions([]);
    },
  });
  const delHoursM = useWrMutation((entryId: string) => deleteHours(id, entryId), {
    onSuccess: () => addToast({ type: 'success', title: t('wr.hours_deleted', { defaultValue: 'Hours entry deleted' }) }),
  });
  const uploadM = useWrMutation((file: File) => uploadAttachment(id, file), {
    onSuccess: (_o, file) => addToast({ type: 'success', title: t('wr.uploaded_file', { defaultValue: 'Attached {{f}}', f: file.name }) }),
  });
  /**
   * One item at a time, keyed so only the box mid-flight goes quiet -
   * disabling the whole list while one tick lands makes a seven-item
   * sign-off feel broken.
   */
  const [tickingKey, setTickingKey] = useState<string | null>(null);
  const tickM = useWrMutation(({ key, done }: { key: string; done: boolean }) => tickChecklist(id, key, done), {
    onSuccess: () => setTickingKey(null),
    onError: (err) => {
      setTickingKey(null);
      setInlineError(errorText(err));
    },
  });

  useEffect(() => {
    if (req) setTitleDraft(req.title);
  }, [req?.title, req]);

  const patch = (p: PatchRequestBody) => void patchM.mutateAsync(p).catch(() => undefined);

  const pool = useMemo(() => memberPool(dept, users.data ?? []), [dept, users.data]);
  const pickerOptions = useMemo(() => {
    if (!picker || !req) return [];
    if (picker.what === 'types') {
      // The live types of this request's own department, plus whatever the
      // request already carries - a type retired since it was raised must
      // still show as ticked rather than silently vanishing on the next save.
      const live = typesOf(dept);
      const extra = typeKeysOf(req)
        .filter((k) => !live.some((x) => x.key === k))
        .map((k) => ({ key: k, label: k, disciplines: [], fields: [] }));
      return [...live, ...extra].map((rt) => ({
        id: rt.key,
        label: rt.label,
        sub: fmtList(rt.disciplines ?? []),
      }));
    }
    if (picker.what === 'dependency') {
      const taken = new Set([req.id, ...req.depends_on.map((d) => d.id)]);
      return (jobRequests.data ?? [])
        .filter((r) => !taken.has(r.id))
        .map((r) => ({ id: r.id, label: r.title, sub: r.reference, lead: <span className="wr-pill" style={tintStyle(deptOf(departments, r.department)?.colour ?? NEUTRAL)}>{deptOf(departments, r.department)?.name ?? r.department}</span> }));
    }
    const list = picker.what === 'mention' ? users.data ?? [] : pool;
    return list.map((u) => ({ id: u.id, label: u.full_name || u.email, sub: u.email, lead: <Avatar person={{ id: u.id, name: u.full_name || u.email }} size={18} /> }));
  }, [picker, req, jobRequests.data, users.data, pool, departments, dept]);

  if (q.isLoading) return <p className="wr-hint p-4">{t('wr.loading', { defaultValue: 'Loading…' })}</p>;
  if (q.isError) {
    if (isModuleMissing(q.error)) return <div className="p-4"><ModuleMissing onRetry={() => void q.refetch()} /></div>;
    return (
      <div className="p-4">
        <div className="wr-empty">
          <b>{t('wr.not_found', { defaultValue: 'This request could not be loaded.' })}</b>
          {errorText(q.error)}
        </div>
      </div>
    );
  }
  if (!req) return null;

  const closed = isClosed(req.status);
  const stages = stagesOf(dept);
  const curIdx = stages.findIndex((s) => s.key === req.stage);
  const ball = ballWords(req, me, dept?.name ?? req.department);
  const due = dueClause(req);
  const actionErr = actions.error && actions.error.id === req.id ? `${actions.error.text}${actions.error.allowed.length ? ` (allowed: ${fmtList(actions.error.allowed)})` : ''}` : null;
  /**
   * A refused closing move on a request that still has required items
   * outstanding belongs BESIDE the boxes that would clear it, not in a
   * banner at the top of a drawer with the checklist scrolled out of
   * sight. The server's sentence is what is shown either way.
   */
  const checklistRefusal = actionErr && outstandingRequired(req).length > 0 ? actionErr : null;
  const inlineErr = inlineError ?? (checklistRefusal ? null : actionErr);
  const items = checklistOf(req);
  const progress = checklistProgress(req);
  // Only the department doing the work signs its own list off.
  const canTick = onDepartmentSide(req, dept, me);
  // Editing the LIST is a different right again - a manager, or the
  // department's lead. The server is the authority; this only decides
  // whether to offer controls that would be refused.
  const canEditList = canEditChecklist(dept, me, canManage);
  const ac = atCompletion(req);
  const dev = req.deviation_hours ?? (ac !== null && req.quoted_hours !== null ? ac - req.quoted_hours : null);
  // Money arrives as Decimal-as-TEXT ("125.00"), so it is coerced before
  // it is multiplied and formatted rather than printed raw.
  const rate = moneyNumber(dept?.hourly_rate);
  const cost = moneyNumber(req.cost_at_completion) ?? (rate !== null && ac !== null ? ac * rate : null);
  // A request can be several types at once (SCADA *and* PLC *and* FDS), so
  // the questions it answers and the disciplines it books hours against are
  // the UNION of them - `field_specs` when the server sends it, worked out
  // from the department's own types when it does not.
  const typeKeys = typeKeysOf(req);
  const typeLabels = typeLabelsOf(req, dept);
  const specs = fieldSpecsOf(req, dept);
  const fromTypes = unionDisciplines(typeKeys.map((k) => dept?.request_types.find((x) => x.key === k)).filter((x): x is NonNullable<typeof x> => !!x));
  const disciplines = fromTypes.length
    ? fromTypes
    : Array.from(new Set([...Object.keys(req.estimated_hours ?? {}), ...Object.keys(req.cost_centres ?? {})]));

  const sectionMenu = (e: ReactMouseEvent, items: (MenuItem | null)[], head: string) => menu.openFromEvent(e, items, { head });

  const openPriority = (el: HTMLElement) =>
    menu.openBelow(
      el,
      PRIORITIES.map<MenuItem>((p) => ({
        label: t(`wr.priority.${p}`, { defaultValue: PRIORITY_LABEL[p] }),
        note: p === req.priority ? t('wr.current', { defaultValue: 'current' }) : undefined,
        disabled: p === req.priority,
        onClick: () => patch({ priority: p as Priority }),
      })),
      { head: t('wr.priority_lbl', { defaultValue: 'Priority' }) },
    );

  const addLink = async () => {
    const r = await qAsk({
      title: t('wr.add_link_title', { defaultValue: 'Add a link' }),
      fields: [
        { label: t('wr.link_label', { defaultValue: 'Label' }), placeholder: t('wr.link_label_ph', { defaultValue: 'e.g. Switchboard GA drawing' }) },
        { label: t('wr.link_url', { defaultValue: 'URL' }), placeholder: 'https://…' },
      ],
      okLabel: t('wr.add', { defaultValue: 'Add' }),
    });
    if (!r) return;
    const url = (r[1] ?? '').trim();
    if (!url) return;
    patch({ links: [...req.links, { label: (r[0] ?? '').trim() || url, url }] });
  };

  const removeLink = (i: number) => patch({ links: req.links.filter((_, j) => j !== i) });

  const insertMention = (u: { id: string; name: string }) => {
    setMentions((m) => (m.some((x) => x.id === u.id) ? m : [...m, u]));
    setComment((c) => `${c.replace(/@$/, '')}@${u.name} `);
    window.setTimeout(() => commentRef.current?.focus(), 10);
  };

  return (
    <div className="wr flex flex-col gap-3 p-4" data-testid="wr-detail">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <RefChip reference={req.reference} colour={dept?.colour} onContextMenu={(e) => actions.openMenu(e, req)} onClick={() => void copyText(req.reference).then((ok) => ok && addToast({ type: 'success', title: t('wr.copied', { defaultValue: 'Copied {{ref}}', ref: req.reference }) }))} title={t('wr.copy_ref', { defaultValue: 'Copy reference' })} />
        <StatusPill status={req.status} />
        <button type="button" className="wr-btn-quiet" onClick={(e) => openPriority(e.currentTarget)} title={t('wr.priority_lbl', { defaultValue: 'Priority' })}>
          <PriorityGlyph priority={req.priority} /> {t(`wr.priority.${req.priority}`, { defaultValue: PRIORITY_LABEL[req.priority] })}
        </button>
        <span className="wr-pill" style={tintStyle(dept?.colour ?? NEUTRAL)}>
          {dept?.name ?? req.department}
        </span>
        <LatePill req={req} />
        {req.is_template && (
          <span className="wr-pill" style={tintStyle('#8a5406')} title={t('wr.is_template_hint', { defaultValue: 'A shape to raise new requests from - hidden from the lists.' })}>
            {t('wr.is_template', { defaultValue: 'template' })}
          </span>
        )}
        <button
          type="button"
          className="wr-btn-quiet ml-auto"
          onClick={() => actions.print(req)}
          title={t('wr.print_hint', { defaultValue: 'A one-page sheet for the workshop floor - or Save as PDF from the print dialog' })}
          data-testid="wr-print-btn"
        >
          <Printer size={12} /> {t('wr.print', { defaultValue: 'Print / Save as PDF' })}
        </button>
        <span>
          <BallPill req={req} me={me} deptName={dept?.name ?? req.department} />
        </span>
      </div>

      {editingTitle ? (
        <input
          className="wr-in text-base font-semibold"
          value={titleDraft}
          autoFocus
          aria-label={t('wr.title_lbl', { defaultValue: 'Title' })}
          onChange={(e) => setTitleDraft(e.target.value)}
          onBlur={() => {
            setEditingTitle(false);
            if (titleDraft.trim() && titleDraft.trim() !== req.title) patch({ title: titleDraft.trim() });
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            if (e.key === 'Escape') {
              setTitleDraft(req.title);
              setEditingTitle(false);
            }
          }}
        />
      ) : (
        <h2 className="m-0 flex items-start gap-2 text-base font-semibold text-content-primary" onContextMenu={(e) => actions.openMenu(e, req)}>
          <span className="min-w-0 flex-1 break-words">{req.title}</span>
          <button type="button" className="wr-btn-quiet shrink-0" onClick={() => setEditingTitle(true)} aria-label={t('wr.edit_title', { defaultValue: 'Edit title' })}>
            <Pencil size={12} />
          </button>
        </h2>
      )}

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Link to={`/projects/${encodeURIComponent(req.project_id)}`} className="wr-chip" onClick={(e) => e.stopPropagation()}>
          <span className="tag" style={tintStyle('#1361c9')}>{t('wr.job', { defaultValue: 'Job' })}</span>
          <span className="lbl">
            <b className="wr-mono">{req.project_code}</b> {req.project_name}
          </span>
        </Link>
        {req.client_name && (
          <span className="wr-chip" style={{ cursor: 'default' }}>
            <span className="tag" style={tintStyle('#0a6f66')}>{t('wr.client', { defaultValue: 'Client' })}</span>
            <span className="lbl">{req.client_name}</span>
          </span>
        )}
        <span className="wr-hint">
          {t('wr.raised_line', { defaultValue: 'Raised by {{who}} · {{when}}', who: req.raised_by_name, when: fmtWhen(req.created_at) })}
        </span>
      </div>

      {inlineErr && (
        <div className="wr-banner err" role="alert">
          <span>{inlineErr}</span>
          <button type="button" className="wr-btn-quiet ml-auto" onClick={() => { setInlineError(null); actions.clearError(); }}>
            ✕
          </button>
        </div>
      )}

      {req.needs_info && (
        <div className="wr-banner info" data-testid="wr-needs-info">
          <div className="flex-1">
            <b>{t('wr.needs_info_banner', { defaultValue: 'The department needs information from {{who}}', who: req.raised_by_id === me?.id ? t('wr.you', { defaultValue: 'you' }) : req.raised_by_name })}</b>
            <div className="mt-1 whitespace-pre-wrap">{req.needs_info}</div>
            <div className="mt-2 flex flex-col gap-1.5">
              <textarea
                className="wr-in"
                value={answer}
                placeholder={t('wr.answer_ph', { defaultValue: 'Your answer…' })}
                aria-label={t('wr.answer', { defaultValue: 'Answer' })}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && answer.trim()) void answerM.mutateAsync(answer.trim()).catch(() => undefined);
                }}
              />
              <div>
                <button type="button" className="wr-btn-quiet on" disabled={!answer.trim() || answerM.isPending} onClick={() => void answerM.mutateAsync(answer.trim()).catch(() => undefined)}>
                  {t('wr.send_answer', { defaultValue: 'Answer' })}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Whose move it is, and how long there is - ONE sentence.
          It used to print the ball pill and the bare due fragment side by
          side, which read "With Workshop. in 57 days"; the lead now has no
          full stop and the distance says what it is a distance to. The
          Dates section below carries the due DATE, this line the distance,
          so the same words are never on the screen twice. */}
      {!req.needs_info && !closed && (
        <div className="wr-banner ball" data-testid="wr-ball-banner">
          <div className="flex-1">
            <b>
              {ball.withYou ? t('wr.ball_with_you', { defaultValue: 'With you' }) : t('wr.ball_with', { defaultValue: 'With {{who}}', who: ball.label.replace(/^with /, '') })}
              {due && (
                <>
                  {' · '}
                  <span className={clsx(due.overdue && 'font-bold text-semantic-error')} data-testid="wr-ball-due">
                    {due.text}
                  </span>
                </>
              )}
            </b>
            {ball.withYou && (
              <div className="mt-0.5 wr-hint">
                {req.ball_in_court === 'requester'
                  ? t('wr.ball_you_requester', { defaultValue: 'The department is waiting on you.' })
                  : t('wr.ball_you_dept', { defaultValue: 'Move it along the stages, or send it back with “Needs info” if something is missing.' })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Stage stepper ───────────────────────────────────────── */}
      {/* Every stage name reads IN FULL inside its own chevron.
          The steps were `flex: 1 1 0` over a `min-width: 96px` floor -
          and an explicit min-width replaces a flex item's automatic
          min-content floor, so eight stages in 838px were squeezed to
          96px each and clipped to "Drawings receiv", "Materials ordere",
          "Rea". They are now `flex: 1 1 auto` over `min-width:
          min-content`: they share spare width when there is any and
          never shrink below their own words, at a slightly smaller size
          than the rest of the drawer so eight of them still fit on one
          row. The scroller stays underneath for a department with more
          stages than any width can hold - its arrows assign `scrollLeft`
          rather than call `scrollBy`, which is a no-op here. */}
      {stages.length > 0 && (
        <HScroll className="wr-steps" label={t('wr.stages', { defaultValue: 'Stages' })} step={200}>
        <div className="wr-steps-in" role="group" aria-label={t('wr.stages', { defaultValue: 'Stages' })}>
          {stages.map((s, i) => {
            const hist = [...req.stage_history].reverse().find((h) => h.stage === s.key);
            const tip = hist
              ? t('wr.stage_hist', { defaultValue: '{{stage}} · {{when}} · {{who}}{{note}}', stage: s.name, when: fmtWhen(hist.at), who: hist.by_name, note: hist.note ? ` · ${hist.note}` : '' })
              : t('wr.stage_move', { defaultValue: 'Move to {{stage}}', stage: s.name });
            return (
              <button
                key={s.key}
                type="button"
                className={clsx('wr-step', i < curIdx && 'done', i === curIdx && 'cur')}
                style={{ ['--st' as string]: resolveColour(s.colour) } as CSSProperties}
                title={tip}
                aria-current={i === curIdx ? 'step' : undefined}
                disabled={i === curIdx}
                onClick={() => void actions.toStage(req, s.key)}
                onContextMenu={(e) => actions.openMenu(e, req)}
              >
                <span className="k">{i + 1}{s.closes ? ` · ${t('wr.closes', { defaultValue: 'closes' })}` : ''}</span>
                <span className="nm" data-testid={`wr-step-name-${s.key}`}>{s.name}</span>
              </button>
            );
          })}
        </div>
        </HScroll>
      )}

      {/* ── Details ─────────────────────────────────────────────── */}
      <Section
        id="details"
        title={t('wr.sec_details', { defaultValue: 'Details' })}
        onContextMenu={(e) =>
          sectionMenu(e, [{ label: t('wr.copy_details', { defaultValue: 'Copy details as text' }), onClick: () => void copyText(`${req.reference} ${req.title}\n${req.project_code} ${req.project_name}\n${req.description ?? ''}`) }], t('wr.sec_details', { defaultValue: 'Details' }))
        }
      >
        <div className="wr-kv">
          <span className="k">{typeLabels.length > 1 ? t('wr.request_types', { defaultValue: 'Request types' }) : t('wr.request_type', { defaultValue: 'Request type' })}</span>
          <span className="v flex flex-wrap items-center gap-1.5" data-testid="wr-detail-types">
            {typeLabels.length === 0 && <span className="wr-hint">—</span>}
            {typeLabels.map((label, i) => (
              <span key={`${typeKeys[i] ?? label}`} className="wr-pill" style={tintStyle(dept?.colour ?? NEUTRAL)}>
                {label}
              </span>
            ))}
            <button
              type="button"
              className="wr-btn-quiet"
              onClick={(e) => setPicker({ at: e.currentTarget, what: 'types' })}
              data-testid="wr-edit-types"
            >
              <Pencil size={11} /> {t('wr.change_types', { defaultValue: 'Change…' })}
            </button>
          </span>
          {specs.map((f) => (
            <FieldRow key={f.key} field={f} value={req.fields?.[f.key]} onSave={(v) => patch({ fields: { ...req.fields, [f.key]: v } })} />
          ))}
          <span className="k">{t('wr.description', { defaultValue: 'Description' })}</span>
          <span className="v">
            <Inline type="area" value={req.description ?? ''} placeholder={t('wr.description_ph', { defaultValue: 'What is needed, by when, and why' })} onSave={(v) => patch({ description: v })} />
          </span>
        </div>
      </Section>

      {/* ── Checklist ───────────────────────────────────────────── */}
      {(items.length > 0 || checklistRefusal || canEditList) && (
        <Section
          id="checklist"
          title={t('wr.sec_checklist', { defaultValue: 'Checklist' })}
          count={progress.total ? <ChecklistProgress req={req} /> : undefined}
        >
          <Checklist
            req={req}
            canTick={canTick && !closed}
            canEdit={canEditList && !closed}
            users={users.data ?? []}
            busyKey={tickingKey}
            refusal={checklistRefusal}
            onDismissRefusal={() => actions.clearError()}
            onTick={(item: ChecklistItem, done: boolean) => {
              setTickingKey(item.key);
              void tickM.mutateAsync({ key: item.key, done }).catch(() => undefined);
            }}
          />
        </Section>
      )}

      {/* ── People ──────────────────────────────────────────────── */}
      <Section
        id="people"
        title={t('wr.sec_people', { defaultValue: 'People' })}
        count={req.assignees.length}
        onContextMenu={(e) =>
          sectionMenu(
            e,
            [
              { label: t('wr.assign_people', { defaultValue: 'Assignees…' }), onClick: () => setPicker({ at: { x: e.clientX, y: e.clientY }, what: 'assignees' }) },
              { label: t('wr.assign_responsible', { defaultValue: 'Responsible…' }), onClick: () => setPicker({ at: { x: e.clientX, y: e.clientY }, what: 'responsible' }) },
            ],
            t('wr.sec_people', { defaultValue: 'People' }),
          )
        }
      >
        <div className="wr-kv">
          <span className="k">{t('wr.raised_by', { defaultValue: 'Raised by' })}</span>
          <span className="v flex items-center gap-2">
            <Avatar person={{ id: req.raised_by_id, name: req.raised_by_name }} /> {req.raised_by_name}
          </span>
          <span className="k">{t('wr.responsible', { defaultValue: 'Responsible' })}</span>
          <span className="v">
            {/* A button's label says what pressing it DOES. "Who is
                responsible?" read as a question the screen was asking
                the reader, not as the control that answers it. */}
            <button
              type="button"
              className="wr-chip"
              onClick={(e) => setPicker({ at: e.currentTarget, what: 'responsible' })}
              title={t('wr.set_responsible_hint', { defaultValue: 'Choose the person accountable for this request' })}
            >
              {req.responsible ? (
                <>
                  <Avatar person={req.responsible} size={18} /> {req.responsible.name}
                </>
              ) : (
                <span className="wr-hint">
                  <Plus size={11} className="inline" /> {t('wr.set_responsible', { defaultValue: 'Set who is responsible…' })}
                </span>
              )}
            </button>
          </span>
          <span className="k">{t('wr.assignees', { defaultValue: 'Assignees' })}</span>
          <span className="v flex flex-wrap items-center gap-1.5">
            <Avatars people={req.assignees} max={8} />
            {req.assignees.length > 0 && <span className="wr-hint">{fmtList(req.assignees.map((a) => a.name))}</span>}
            <button type="button" className="wr-btn-quiet" onClick={(e) => setPicker({ at: e.currentTarget, what: 'assignees' })}>
              <Plus size={11} />{' '}
              {req.assignees.length > 0
                ? t('wr.change_assignees', { defaultValue: 'Change who is assigned…' })
                : t('wr.add_assignees', { defaultValue: 'Assign people…' })}
            </button>
          </span>
        </div>
      </Section>

      {/* ── Dates ───────────────────────────────────────────────── */}
      <Section id="dates" title={t('wr.sec_dates', { defaultValue: 'Dates' })}>
        <div className="wr-kv">
          {(
            [
              ['info_required_by', t('wr.info_by', { defaultValue: 'Info required by' })],
              ['due_date', t('wr.due', { defaultValue: 'Due' })],
              ['scheduled_start', t('wr.sched_start', { defaultValue: 'Scheduled start' })],
              ['scheduled_end', t('wr.sched_end', { defaultValue: 'Scheduled end' })],
              ['delivered_at', t('wr.delivered', { defaultValue: 'Delivered' })],
              ['tested_at', t('wr.tested', { defaultValue: 'Tested' })],
            ] as const
          ).map(([key, label]) => (
            /* The native date input renders in the BROWSER's locale, so
               "05/10/2026" is 5 October to one reader and 10 May to
               another; the app's own `fmtDate` beside it settles it. The
               DUE row carries the date only - the distance ("due in 57
               days") is on the banner, and saying it twice on one screen
               is how "in 57 days" ended up under itself. */
            <FragmentRow key={key} label={label}>
              <Inline type="date" value={(req[key] ?? '').slice(0, 10)} onSave={(v) => patch({ [key]: v || null } as PatchRequestBody)} />
              {req[key] && <span className="ml-2 wr-hint">{fmtDay(req[key])}</span>}
              {key === 'due_date' && req.due_date && req.is_overdue && (
                <span className="ml-2 font-bold text-semantic-error">{t('wr.overdue', { defaultValue: 'overdue' })}</span>
              )}
            </FragmentRow>
          ))}
        </div>
      </Section>

      {/* ── Hours & cost ────────────────────────────────────────── */}
      <Section
        id="hours"
        title={t('wr.sec_hours', { defaultValue: 'Hours & cost' })}
        count={fmtHours(req.hours_logged)}
        right={
          <button type="button" className="wr-btn-quiet" onClick={() => void actions.logTime(req)}>
            {t('wr.log_hours', { defaultValue: 'Log hours…' })}
          </button>
        }
        onContextMenu={(e) => sectionMenu(e, [{ label: t('wr.log_hours', { defaultValue: 'Log hours…' }), onClick: () => void actions.logTime(req) }], t('wr.sec_hours', { defaultValue: 'Hours & cost' }))}
      >
        <div className="mb-2">
          <HoursBar req={req} />
        </div>
        <div className="wr-kv">
          <span className="k">{t('wr.quoted', { defaultValue: 'Quoted' })}</span>
          <span className="v">
            <Inline type="number" value={req.quoted_hours === null ? '' : String(req.quoted_hours)} suffix="h" onSave={(v) => patch({ quoted_hours: v === '' ? null : Number(v) })} />
          </span>
          {disciplines.length > 0 && (
            <>
              <span className="k">{t('wr.per_discipline', { defaultValue: 'Estimated · cost centre' })}</span>
              <span className="v">
                <div className="wr-disc">
                  <span className="h">{t('wr.discipline', { defaultValue: 'Discipline' })}</span>
                  <span className="h">{t('wr.cost_centre', { defaultValue: 'Cost centre' })}</span>
                  <span className="h">{t('wr.est_hours', { defaultValue: 'Est. hours' })}</span>
                  {disciplines.map((d) => (
                    <FragmentTriple key={d}>
                      <span>{d}</span>
                      <Inline value={req.cost_centres?.[d] ?? ''} placeholder="—" onSave={(v) => patch({ cost_centres: { ...req.cost_centres, [d]: v } })} />
                      <Inline type="number" value={req.estimated_hours?.[d] === undefined ? '' : String(req.estimated_hours[d])} suffix="h" onSave={(v) => patch({ estimated_hours: { ...req.estimated_hours, [d]: v === '' ? 0 : Number(v) } })} />
                    </FragmentTriple>
                  ))}
                </div>
              </span>
            </>
          )}
          <span className="k">{t('wr.logged', { defaultValue: 'Logged' })}</span>
          <span className="v">
            {fmtHours(req.hours_logged)}
            {hours.data && hours.data.length > 0 && (
              <table className="mt-1 w-full text-xs">
                <tbody>
                  {hours.data.map((h) => (
                    <tr key={h.id} className="border-t border-border-light">
                      <td className="py-1 pr-2 whitespace-nowrap">{fmtDay(h.date)}</td>
                      <td className="py-1 pr-2 whitespace-nowrap">{h.user_name}</td>
                      <td className="py-1 pr-2 text-right font-mono whitespace-nowrap">{fmtHours(h.hours)}</td>
                      <td className="py-1 pr-2 text-content-tertiary">{h.note}</td>
                      <td className="py-1 text-right">
                        <button
                          type="button"
                          className="wr-btn-quiet"
                          aria-label={t('wr.delete_hours', { defaultValue: 'Delete this entry' })}
                          onClick={async () => {
                            if (await qConfirm(t('wr.delete_hours_q', { defaultValue: 'Delete {{h}} logged on {{d}}?', h: fmtHours(h.hours), d: fmtDay(h.date) }))) void delHoursM.mutateAsync(h.id).catch(() => undefined);
                          }}
                        >
                          <Trash2 size={11} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </span>
          <span className="k">{t('wr.to_complete', { defaultValue: 'To complete' })}</span>
          <span className="v">
            <Inline type="number" value={req.hours_to_complete === null ? '' : String(req.hours_to_complete)} suffix="h" onSave={(v) => patch({ hours_to_complete: v === '' ? null : Number(v) })} />
          </span>
          <span className="k">{t('wr.at_completion', { defaultValue: 'At completion' })}</span>
          <span className="v">{fmtHours(ac)}</span>
          <span className="k">{t('wr.deviation', { defaultValue: 'Deviation' })}</span>
          <span className={clsx('v wr-dev', dev !== null && dev > 0 && 'over', dev !== null && dev < 0 && 'under')}>
            {fmtDeviation(dev)}
            {dev !== null && dev !== 0 && <span className="wr-hint ml-2">{dev > 0 ? t('wr.over_quote', { defaultValue: 'over the quote' }) : t('wr.under_quote', { defaultValue: 'under the quote' })}</span>}
          </span>
          <span className="k">{t('wr.cost_at_completion', { defaultValue: 'Cost at completion' })}</span>
          <span className="v">
            {cost === null ? (
              <span className="wr-hint">
                {t('wr.no_rate', { defaultValue: 'No hourly rate on {{dept}} yet', dept: dept?.name ?? req.department })}
              </span>
            ) : (
              <>
                {fmtMoney(cost)}
                {rate !== null && (
                  <span className="wr-hint ml-2">{t('wr.rate_hint', { defaultValue: '@ {{r}}/h', r: fmtMoney(rate) })}</span>
                )}
              </>
            )}
          </span>
        </div>
      </Section>

      {/* ── Dependencies & handoffs ─────────────────────────────── */}
      <Section
        id="deps"
        title={t('wr.sec_deps', { defaultValue: 'Dependencies & handoffs' })}
        count={req.depends_on.length + req.blocks.length + req.children.length + (req.parent_id ? 1 : 0)}
        right={
          <>
            <button type="button" className="wr-btn-quiet" onClick={(e) => setPicker({ at: e.currentTarget, what: 'dependency' })}>
              {t('wr.add_dependency', { defaultValue: 'Add dependency…' })}
            </button>
            <button type="button" className="wr-btn-quiet" onClick={() => actions.handoff(req)} disabled={closed}>
              {t('wr.handoff_btn', { defaultValue: 'Hand off to another department…' })}
            </button>
          </>
        }
        onContextMenu={(e) =>
          sectionMenu(
            e,
            [
              { label: t('wr.add_dependency', { defaultValue: 'Add dependency…' }), onClick: () => setPicker({ at: { x: e.clientX, y: e.clientY }, what: 'dependency' }) },
              { label: t('wr.handoff_btn', { defaultValue: 'Hand off to another department…' }), disabled: closed, onClick: () => actions.handoff(req) },
            ],
            t('wr.sec_deps', { defaultValue: 'Dependencies & handoffs' }),
          )
        }
      >
        <div className="wr-kv">
          <RelatedRow label={t('wr.depends_on', { defaultValue: 'Depends on' })} items={req.depends_on} departments={departments} onOpen={onOpenOther} onRemove={(r) => patch({ depends_on_ids: req.depends_on.filter((d) => d.id !== r.id).map((d) => d.id) })} menu={menu} empty={t('wr.no_deps', { defaultValue: 'Nothing - this can start now.' })} />
          <RelatedRow label={t('wr.blocks', { defaultValue: 'Blocks' })} items={req.blocks} departments={departments} onOpen={onOpenOther} menu={menu} empty={t('wr.no_blocks', { defaultValue: 'Nothing waits on this.' })} />
          <RelatedRow
            label={t('wr.parent', { defaultValue: 'Parent' })}
            items={req.parent_id ? [{ id: req.parent_id, reference: req.parent_reference ?? req.parent_id, title: '', status: 'submitted', department: '' }] : []}
            departments={departments}
            onOpen={onOpenOther}
            menu={menu}
            empty={t('wr.no_parent', { defaultValue: 'Raised directly.' })}
          />
          <RelatedRow label={t('wr.children', { defaultValue: 'Handed off as' })} items={req.children} departments={departments} onOpen={onOpenOther} menu={menu} empty={t('wr.no_children', { defaultValue: 'Not handed off anywhere.' })} />
        </div>
      </Section>

      {/* ── Feeds: the programme and the estimate ───────────────── */}
      <Section
        id="feeds"
        title={t('wr.sec_feeds', { defaultValue: 'Feeds' })}
        count={(req.schedule_activity_id ? 1 : 0) + (req.boq_position_ids?.length ?? 0) || undefined}
        defaultOpen={false}
      >
        <p className="wr-hint mb-2">
          {t('wr.feeds_hint', { defaultValue: 'What this request feeds: the programme line it belongs to, and the estimate positions it is booked against.' })}
        </p>
        <Feeds req={req} onChange={(p) => patch(p)} />
      </Section>

      {/* ── Links & attachments ─────────────────────────────────── */}
      <Section
        id="links"
        title={t('wr.sec_links', { defaultValue: 'Links & attachments' })}
        count={req.links.length + req.attachments.length}
        right={
          <>
            <button type="button" className="wr-btn-quiet" onClick={() => void addLink()}>
              {t('wr.add_link', { defaultValue: 'Add link…' })}
            </button>
            <button type="button" className="wr-btn-quiet" onClick={() => fileRef.current?.click()} disabled={uploadM.isPending}>
              <Upload size={11} /> {uploadM.isPending ? t('wr.uploading', { defaultValue: 'Uploading…' }) : t('wr.upload', { defaultValue: 'Upload…' })}
            </button>
            <input
              ref={fileRef}
              type="file"
              hidden
              aria-label={t('wr.upload', { defaultValue: 'Upload…' })}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void uploadM.mutateAsync(f).catch(() => undefined);
                e.target.value = '';
              }}
            />
          </>
        }
        onContextMenu={(e) =>
          sectionMenu(
            e,
            [
              { label: t('wr.add_link', { defaultValue: 'Add link…' }), onClick: () => void addLink() },
              { label: t('wr.upload', { defaultValue: 'Upload…' }), onClick: () => fileRef.current?.click() },
            ],
            t('wr.sec_links', { defaultValue: 'Links & attachments' }),
          )
        }
      >
        <div className="flex flex-wrap gap-1.5">
          {req.links.map((l, i) => (
            <a
              key={`${l.url}-${i}`}
              className="wr-chip"
              href={l.url}
              target="_blank"
              rel="noopener noreferrer"
              title={l.label ? `${l.label} — ${l.url}` : l.url}
              onContextMenu={(e) =>
                menu.openFromEvent(
                  e,
                  [
                    { label: t('wr.open', { defaultValue: 'Open' }), onClick: () => window.open(l.url, '_blank', 'noopener') },
                    { label: t('wr.copy_url', { defaultValue: 'Copy URL' }), onClick: () => void copyText(l.url) },
                    null,
                    { label: t('wr.remove_link', { defaultValue: 'Remove link' }), danger: true, onClick: () => removeLink(i) },
                  ],
                  { head: l.label },
                )
              }
            >
              <span className="tag" style={tintStyle('#06657f')}>{t('wr.link_url', { defaultValue: 'URL' })}</span>
              <span className="lbl">{l.label || shortUrl(l.url)}</span>
            </a>
          ))}
          {req.attachments.map((a) => (
            <button
              key={a.filename}
              type="button"
              className="wr-chip"
              title={`${fmtFixed(a.size / 1024, 0)} KB · ${fmtWhen(a.uploaded_at)}`}
              onClick={() => void downloadWithAuth(attachmentUrl(req.id, a.filename), a.filename).catch((err) => addToast({ type: 'error', title: errorText(err) }))}
              onContextMenu={(e) =>
                menu.openFromEvent(e, [{ label: t('wr.download', { defaultValue: 'Download' }), onClick: () => void downloadWithAuth(attachmentUrl(req.id, a.filename), a.filename).catch(() => undefined) }], { head: a.filename })
              }
            >
              <Paperclip size={11} />
              <span className="lbl">{a.filename}</span>
            </button>
          ))}
          {req.links.length === 0 && req.attachments.length === 0 && <span className="wr-hint">{t('wr.no_links', { defaultValue: 'No links or files yet.' })}</span>}
        </div>
      </Section>

      {/* ── Conversation ────────────────────────────────────────── */}
      <Section
        id="conversation"
        title={t('wr.sec_conversation', { defaultValue: 'Conversation' })}
        count={comments.data?.length ?? req.comment_count}
        onContextMenu={(e) => sectionMenu(e, [{ label: t('wr.needs_info', { defaultValue: 'Needs info…' }), disabled: closed, onClick: () => void actions.askInfo(req) }], t('wr.sec_conversation', { defaultValue: 'Conversation' }))}
      >
        <div className="flex flex-col gap-2">
          {(comments.data ?? []).map((c) => (
            <div key={c.id} className={clsx('wr-msg', c.kind)}>
              <div className="who">
                <b>{c.author_name}</b>
                <span>{fmtWhen(c.created_at)}</span>
                {c.kind === 'needs_info' && <span>· {t('wr.kind_needs_info', { defaultValue: 'needs info' })}</span>}
                {c.kind === 'answer' && <span>· {t('wr.kind_answer', { defaultValue: 'answer' })}</span>}
              </div>
              <div className="body">{renderMentions(c.body)}</div>
            </div>
          ))}
          {comments.data && comments.data.length === 0 && <span className="wr-hint">{t('wr.no_comments', { defaultValue: 'No comments yet.' })}</span>}
          <textarea
            ref={commentRef}
            className="wr-in"
            value={comment}
            placeholder={t('wr.comment_ph', { defaultValue: 'Write a comment - type @ to mention someone' })}
            aria-label={t('wr.comment', { defaultValue: 'Comment' })}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === '@') setPicker({ at: e.currentTarget, what: 'mention' });
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && comment.trim()) void commentM.mutateAsync({ body: comment.trim(), ids: mentions.map((m) => m.id) }).catch(() => undefined);
            }}
          />
          <div className="flex items-center gap-2">
            <button type="button" className="wr-btn-quiet" onClick={(e) => setPicker({ at: e.currentTarget, what: 'mention' })}>
              @ {t('wr.mention', { defaultValue: 'Mention' })}
            </button>
            {mentions.length > 0 && <span className="wr-hint">{mentions.map((m) => `@${m.name}`).join(' ')}</span>}
            <button type="button" className="wr-btn-quiet on ml-auto" disabled={!comment.trim() || commentM.isPending} onClick={() => void commentM.mutateAsync({ body: comment.trim(), ids: mentions.map((m) => m.id) }).catch(() => undefined)}>
              {t('wr.post', { defaultValue: 'Post' })}
            </button>
          </div>
        </div>
      </Section>

      {/* ── Activity ────────────────────────────────────────────── */}
      <Section id="activity" title={t('wr.sec_activity', { defaultValue: 'Activity' })} count={activity.data?.length} defaultOpen={false}>
        {activity.data && activity.data.length > 0 ? (
          <div className="wr-tl">
            {activity.data.map((a, i) => (
              <div key={`${a.at}-${i}`}>
                <div>
                  <b>{a.what}</b> {a.detail && <span className="text-content-secondary">— {a.detail}</span>}
                </div>
                <div className="when">
                  {fmtWhen(a.at)} · {a.by_name}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <span className="wr-hint">{activity.isLoading ? t('wr.loading', { defaultValue: 'Loading…' }) : t('wr.no_activity', { defaultValue: 'Nothing recorded yet.' })}</span>
        )}
      </Section>

      {menu.element}
      {picker && (
        <Picker
          anchor={picker.at}
          options={pickerOptions}
          multi={picker.what === 'assignees' || picker.what === 'types'}
          selected={
            picker.what === 'types'
              ? typeKeys
              : picker.what === 'assignees'
                ? req.assignees.map((a) => a.id)
                : picker.what === 'responsible' && req.responsible
                  ? [req.responsible.id]
                  : []
          }
          placeholder={
            picker.what === 'types'
              ? t('wr.pick_types', { defaultValue: 'Which types is this? Pick every one.' })
              : picker.what === 'dependency'
                ? t('wr.pick_dependency', { defaultValue: 'Which request must finish first?' })
                : picker.what === 'mention'
                  ? t('wr.pick_mention', { defaultValue: 'Mention…' })
                  : picker.what === 'assignees'
                    ? t('wr.pick_assignees', { defaultValue: 'Assign people…' })
                    : t('wr.pick_responsible', { defaultValue: 'Who is responsible?' })
          }
          emptyText={picker.what === 'dependency' ? t('wr.no_other_requests', { defaultValue: 'No other open request on this job.' }) : undefined}
          onClose={() => setPicker(null)}
          onChange={(ids) => {
            // At least one type, always: an empty pick is a slip, not an
            // instruction to make the request typeless, so it is refused
            // here rather than posted for the server to reject.
            if (picker.what === 'types') {
              if (ids.length === 0) {
                setInlineError(t('wr.err_type', { defaultValue: 'Pick at least one request type.' }));
                return;
              }
              patch({ request_types: ids });
            }
            if (picker.what === 'dependency' && ids[0]) patch({ depends_on_ids: [...req.depends_on.map((d) => d.id), ids[0]] });
            if (picker.what === 'mention' && ids[0]) {
              const u = (users.data ?? []).find((x) => x.id === ids[0]);
              if (u) insertMention({ id: u.id, name: u.full_name || u.email });
            }
            if (picker.what === 'assignees') void assignViaApi(req, ids, undefined);
            if (picker.what === 'responsible') void assignViaApi(req, req.assignees.map((a) => a.id), ids[0] ?? null);
          }}
        />
      )}
    </div>
  );

  /* The picker here already knows the ids, so the assignment is one
     direct call; the shared invalidation refreshes every list. */
  async function assignViaApi(r: WorkRequest, ids: string[], responsible: string | null | undefined) {
    try {
      await assignRequest(r.id, ids, responsible);
      void invalidate();
    } catch (err) {
      addToast({ type: 'error', title: errorText(err) });
    }
  }
}

/* ── Small pieces ─────────────────────────────────────────────────── */

function FragmentRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <span className="k">{label}</span>
      <span className="v flex items-center">{children}</span>
    </>
  );
}

function FragmentTriple({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

function FieldRow({ field, value, onSave }: { field: RequestField; value: unknown; onSave: (v: unknown) => void }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const str = value === null || value === undefined ? '' : String(value);
  return (
    <>
      <span className="k">{field.label}</span>
      <span className="v">
        {field.type === 'bool' ? (
          <label className="wr-tog">
            <input type="checkbox" checked={!!value} onChange={(e) => onSave(e.target.checked)} /> {value ? 'Yes' : 'No'}
          </label>
        ) : field.type === 'select' ? (
          <select className="wr-inl" value={str} onChange={(e) => onSave(e.target.value)}>
            <option value="">—</option>
            {(field.options ?? []).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        ) : field.type === 'url' && str ? (
          // A full URL printed at its natural length wrapped over three
          // lines AND repeated itself in an editor that ran off the edge
          // of the drawer. One chip that opens it, one pencil that edits.
          <span className="flex min-w-0 items-center gap-2">
            {editing ? (
              <Inline value={str} type="text" onSave={(v) => { setEditing(false); onSave(v); }} placeholder="https://…" />
            ) : (
              <>
                <a href={str} target="_blank" rel="noopener noreferrer" className="wr-chip min-w-0" title={str}>
                  <span className="tag" style={tintStyle('#06657f')}>{t('wr.link_url', { defaultValue: 'URL' })}</span>
                  {/* The host and the last meaningful segment; the whole
                      url is the href and the tooltip, so nothing is lost
                      and the row is no longer one long machine string. */}
                  <span className="lbl">{shortUrl(str)}</span>
                </a>
                <button type="button" className="wr-btn-quiet shrink-0" onClick={() => setEditing(true)} aria-label={t('wr.edit_link', { defaultValue: 'Edit link' })}>
                  <Pencil size={11} />
                </button>
              </>
            )}
          </span>
        ) : (
          <span className="inline-flex flex-wrap items-center">
            <Inline value={str} type={field.type === 'area' ? 'area' : field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'} onSave={(v) => onSave(field.type === 'number' ? (v === '' ? null : Number(v)) : v)} />
            {/* A native date input renders in the BROWSER's locale, so
                "05/10/2026" is 5 October to one reader and 10 May to
                another. The app's own format beside it settles it - the
                same thing the Dates section does. */}
            {field.type === 'date' && str && <span className="ml-2 wr-hint">{fmtDay(str)}</span>}
          </span>
        )}
      </span>
    </>
  );
}

/** Click-to-edit value: Enter/blur saves, Escape reverts. */
export function Inline({
  value,
  type = 'text',
  placeholder,
  suffix,
  onSave,
}: {
  value: string;
  type?: 'text' | 'number' | 'date' | 'area';
  placeholder?: string;
  suffix?: string;
  onSave: (v: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onSave(draft);
  };
  const common = {
    className: clsx('wr-inl', !draft && 'empty'),
    value: draft,
    placeholder: placeholder ?? '—',
    onBlur: commit,
    onKeyDown: (e: React.KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      if (e.key === 'Escape') {
        setDraft(value);
        (e.target as HTMLElement).blur();
      } else if (e.key === 'Enter' && (type !== 'area' || e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        (e.target as HTMLElement).blur();
      }
    },
  };
  if (type === 'area') {
    return <textarea {...common} rows={draft.split('\n').length > 2 ? 4 : 2} style={{ width: '100%', minWidth: 200 }} onChange={(e) => setDraft(e.target.value)} />;
  }
  return (
    <span className="inline-flex items-center gap-1">
      <input {...common} type={type === 'number' ? 'text' : type} inputMode={type === 'number' ? 'decimal' : undefined} onChange={(e) => setDraft(type === 'number' ? e.target.value.replace(/[^\d.,-]/g, '') : e.target.value)} />
      {suffix && draft && <span className="wr-hint">{suffix}</span>}
    </span>
  );
}

function RelatedRow({
  label,
  items,
  departments,
  onOpen,
  onRemove,
  menu,
  empty,
}: {
  label: string;
  items: RelatedRequest[];
  departments: Department[];
  onOpen: (r: RelatedRequest) => void;
  onRemove?: (r: RelatedRequest) => void;
  menu: ReturnType<typeof useMenu>;
  empty: string;
}) {
  const { t } = useTranslation();
  return (
    <>
      <span className="k">{label}</span>
      <span className="v flex flex-wrap gap-1.5">
        {items.length === 0 && <span className="wr-hint">{empty}</span>}
        {items.map((r) => {
          const d = deptOf(departments, r.department);
          return (
            <button
              key={r.id}
              type="button"
              className="wr-chip"
              onClick={() => onOpen(r)}
              title={r.title}
              onContextMenu={(e) =>
                menu.openFromEvent(
                  e,
                  [
                    { label: t('wr.open', { defaultValue: 'Open' }), onClick: () => onOpen(r) },
                    { label: t('wr.copy_ref', { defaultValue: 'Copy reference' }), note: r.reference, onClick: () => void copyText(r.reference) },
                    ...(onRemove ? [null, { label: t('wr.remove_dependency', { defaultValue: 'Remove dependency' }), danger: true, onClick: () => onRemove(r) }] : []),
                  ],
                  { head: r.reference },
                )
              }
            >
              <span className="tag" style={tintStyle(d?.colour ?? STATUS_COLOUR[r.status] ?? NEUTRAL)}>
                {d?.name ?? r.department ?? '—'}
              </span>
              <span className="wr-mono">{r.reference}</span>
              {r.title && <span className="lbl">{r.title}</span>}
              {isClosed(r.status) && <span className="wr-hint">✓</span>}
            </button>
          );
        })}
      </span>
    </>
  );
}

/** `@Name` tokens in a comment body, highlighted. */
function renderMentions(body: string) {
  const parts = body.split(/(@[A-Za-z][\w'-]*(?: [A-Z][\w'-]*)?)/g);
  return parts.map((p, i) => (p.startsWith('@') ? <span key={i} className="mention">{p}</span> : <span key={i}>{p}</span>));
}
