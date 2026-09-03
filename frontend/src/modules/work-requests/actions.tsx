// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The one right-click menu every request wears - on a board card, a table
 * row, the drawer header - and the writes behind it. Built once per screen
 * with `useRequestActions`, so the board and the list cannot drift apart on
 * what "Move to stage" or "Hand off" means.
 *
 * A 409 from the server (an illegal transition) is NOT toasted away: it is
 * kept on `error` so the screen shows the server's own words inline, with
 * the transitions it would have allowed.
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRightLeft,
  CheckCircle2,
  Clock,
  Copy,
  CopyPlus,
  ExternalLink,
  FolderOpen,
  HelpCircle,
  Printer,
  Star,
  Users,
} from 'lucide-react';
import clsx from 'clsx';
import { useToastStore } from '@/stores/useToastStore';
import { WideModal } from '@/shared/ui';
import { useMenu, type MenuItem } from '../comms-intelligence/ContextMenu';
import { qAsk } from '../comms-intelligence/qAsk';
import {
  askForInfo,
  assignRequest,
  duplicateRequest,
  handoffRequest,
  logHours,
  moveStage,
  patchRequest,
  type Department,
  type HandoffBody,
  type WorkRequest,
} from './api';
import { useUsers, useWrMutation } from './hooks';
import { Picker, type PickAnchor } from './Pickers';
import { RequestPrintSheet } from './PrintSheet';
import { Avatar } from './bits';
import {
  STATUS_LABEL,
  conflictOf,
  copyText,
  deptOf,
  errorText,
  isClosed,
  isoDay,
  memberPool,
  resolveColour,
  stagesOf,
  statusPath,
  typesOf,
  type Me,
} from './lib';

export interface ActionError {
  id: string;
  reference: string;
  text: string;
  allowed: string[];
}

export interface RequestActions {
  /** The menu items for one request; open them with `openMenu`. */
  menuFor: (req: WorkRequest) => (MenuItem | null)[];
  /** Right-click handler for any element that stands for a request. */
  openMenu: (e: React.MouseEvent, req: WorkRequest) => void;
  /** Move a request to a stage (asks for a note on a closing stage). */
  toStage: (req: WorkRequest, stage: string) => Promise<void>;
  askInfo: (req: WorkRequest) => Promise<void>;
  logTime: (req: WorkRequest) => Promise<void>;
  complete: (req: WorkRequest) => Promise<void>;
  setStatus: (req: WorkRequest, status: WorkRequest['status']) => Promise<void>;
  /**
   * Drop a card on a status column. Walks the machine's intermediate
   * steps (Submitted → In progress needs an Accept first) so one gesture
   * means one outcome; a move the machine has no route for still shows
   * the server's own 409 inline.
   */
  toStatusColumn: (req: WorkRequest, status: WorkRequest['status']) => Promise<void>;
  assign: (req: WorkRequest, at: PickAnchor, what: 'assignees' | 'responsible') => void;
  handoff: (req: WorkRequest, department?: string) => void;
  /** Copy the request as a fresh draft, asking for its title first. */
  duplicate: (req: WorkRequest) => Promise<void>;
  /** Mark or unmark the request as a template to raise from. */
  setTemplate: (req: WorkRequest, on: boolean) => Promise<void>;
  /** Open the printable sheet (and the browser's print dialog). */
  print: (req: WorkRequest) => void;
  /** The last refused write, for an inline banner. */
  error: ActionError | null;
  clearError: () => void;
  /** Render once in the screen's tree: the menu, the picker, the dialog. */
  element: ReactNode;
}

export function useRequestActions({
  departments,
  onOpen,
}: {
  departments: Department[] | undefined;
  /** Accepted for symmetry with the views; the menu itself is the same for everyone. */
  me?: Me | null;
  onOpen: (req: WorkRequest) => void;
}): RequestActions {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const menu = useMenu();
  const users = useUsers();
  const [error, setError] = useState<ActionError | null>(null);
  const [picker, setPicker] = useState<{ req: WorkRequest; at: PickAnchor; what: 'assignees' | 'responsible' } | null>(null);
  const [handoffFor, setHandoffFor] = useState<{ req: WorkRequest; department?: string } | null>(null);
  const [logFor, setLogFor] = useState<WorkRequest | null>(null);
  /** The request whose printable sheet is mounted, if any. */
  const [printFor, setPrintFor] = useState<WorkRequest | null>(null);

  const refuse = useCallback((req: WorkRequest, err: unknown) => {
    const c = conflictOf(err);
    if (c) {
      setError({ id: req.id, reference: req.reference, text: c.error, allowed: c.allowed });
      return;
    }
    addToast({ type: 'error', title: errorText(err) });
  }, [addToast]);

  const stageM = useWrMutation(
    ({ req, stage, note }: { req: WorkRequest; stage: string; note?: string }) => (note ? moveStage(req.id, stage, note) : moveStage(req.id, stage)),
    { onError: (err, { req }) => refuse(req, err), onSuccess: () => setError(null) },
  );
  const patchM = useWrMutation(
    ({ req, patch }: { req: WorkRequest; patch: Parameters<typeof patchRequest>[1] }) => patchRequest(req.id, patch),
    { onError: (err, { req }) => refuse(req, err), onSuccess: () => setError(null) },
  );
  const infoM = useWrMutation(({ req, q }: { req: WorkRequest; q: string }) => askForInfo(req.id, q), {
    onSuccess: (_o, { req }) =>
      addToast({ type: 'success', title: t('wr.info_asked', { defaultValue: '{{ref}} sent back to the requester', ref: req.reference }) }),
  });
  const hoursM = useWrMutation(
    ({ req, date, hours, note }: { req: WorkRequest; date: string; hours: number; note?: string }) =>
      logHours(req.id, note ? { date, hours, note } : { date, hours }),
    { onSuccess: (_o, { req, hours }) => addToast({ type: 'success', title: t('wr.hours_logged', { defaultValue: '{{h}}h logged on {{ref}}', h: hours, ref: req.reference }) }) },
  );
  const assignM = useWrMutation(
    ({ req, ids, responsible }: { req: WorkRequest; ids: string[]; responsible?: string | null }) => assignRequest(req.id, ids, responsible),
  );
  const dupM = useWrMutation(({ req, title }: { req: WorkRequest; title?: string }) => duplicateRequest(req.id, title ? { title } : {}), {
    onSuccess: (copy) =>
      addToast({
        type: 'success',
        title: t('wr.duplicated', { defaultValue: 'Copied as {{ref}}', ref: copy.reference }),
        message: copy.title,
        action: { label: t('wr.open', { defaultValue: 'Open' }), onClick: () => onOpen(copy) },
      }),
  });
  const handoffM = useWrMutation(({ req, body }: { req: WorkRequest; body: HandoffBody }) => handoffRequest(req.id, body), {
    onSuccess: (child) => {
      setHandoffFor(null);
      addToast({
        type: 'success',
        title: t('wr.handed_off', { defaultValue: 'Handed off as {{ref}}', ref: child.reference }),
        action: { label: t('wr.open', { defaultValue: 'Open' }), onClick: () => onOpen(child) },
      });
    },
  });

  const toStage = useCallback(
    async (req: WorkRequest, stage: string) => {
      const dept = deptOf(departments, req.department);
      const s = dept?.stages.find((x) => x.key === stage);
      if (!s || s.key === req.stage) return;
      let note: string | undefined;
      if (s.closes) {
        const r = await qAsk({
          title: t('wr.close_title', { defaultValue: 'Move {{ref}} to {{stage}}?', ref: req.reference, stage: s.name }),
          note: t('wr.close_note', { defaultValue: 'This stage closes the request. A note goes on its history.' }),
          fields: [{ label: t('wr.note', { defaultValue: 'Note (optional)' }), placeholder: t('wr.note_ph', { defaultValue: 'e.g. delivered to site, signed off by…' }) }],
          okLabel: t('wr.move', { defaultValue: 'Move' }),
        });
        if (r === null) return;
        note = r[0]?.trim() || undefined;
      }
      await stageM.mutateAsync({ req, stage, note }).catch(() => undefined);
    },
    [departments, stageM, t],
  );

  const askInfo = useCallback(
    async (req: WorkRequest) => {
      const r = await qAsk({
        title: t('wr.needs_info_title', { defaultValue: 'What do you need from {{who}}?', who: req.raised_by_name || 'the requester' }),
        note: t('wr.needs_info_note', { defaultValue: 'The request goes back to the requester until they answer.' }),
        fields: [{ label: t('wr.question', { defaultValue: 'Question' }), multiline: true, placeholder: t('wr.question_ph', { defaultValue: 'e.g. Which switchboard form - 3b or 4a?' }) }],
        okLabel: t('wr.send_back', { defaultValue: 'Send back' }),
      });
      const q = r?.[0]?.trim();
      if (!q) return;
      await infoM.mutateAsync({ req, q }).catch(() => undefined);
    },
    [infoM, t],
  );

  /**
   * Logging hours opens its own dialog rather than the generic ask.
   *
   * The ask has only free-text fields, so the date was typed as a literal
   * `YYYY-MM-DD` and validated by regex - the ONE date in the module that
   * was not the browser's own picker, on a screen where every other date
   * (due, info-required-by, scheduled start) is `<input type="date">` and
   * reads dd/mm. A native picker cannot produce a malformed date, so the
   * "must be YYYY-MM-DD" refusal has nothing left to refuse.
   */
  const logTime = useCallback(async (req: WorkRequest) => {
    setLogFor(req);
  }, []);

  const setStatus = useCallback(
    async (req: WorkRequest, status: WorkRequest['status']) => {
      await patchM.mutateAsync({ req, patch: { status } }).catch(() => undefined);
    },
    [patchM],
  );

  const toStatusColumn = useCallback(
    async (req: WorkRequest, status: WorkRequest['status']) => {
      if (status === req.status) return;
      const hops = statusPath(req.status, status, req.allowed_transitions);
      // No route at all (a terminal state, say): let the server say so,
      // in its own words, with the transitions it would have taken.
      if (hops === null || hops.length === 0) {
        await setStatus(req, status);
        return;
      }
      for (const hop of hops) {
        // eslint-disable-next-line no-await-in-loop -- the machine is a chain; hop 2 is only legal once hop 1 lands
        const out = await patchM.mutateAsync({ req, patch: { status: hop } }).catch(() => null);
        if (out === null) return; // refused: the banner already says why
      }
      if (hops.length > 1) {
        addToast({
          type: 'success',
          title: t('wr.status_stepped', {
            defaultValue: '{{ref}} accepted, then moved to {{status}}',
            ref: req.reference,
            status: t(`wr.status.${status}`, { defaultValue: STATUS_LABEL[status] }),
          }),
        });
      }
    },
    [addToast, patchM, setStatus, t],
  );

  const complete = useCallback((req: WorkRequest) => toStatusColumn(req, 'complete'), [toStatusColumn]);

  /**
   * Duplicate asks for the title first. A copy called "MSB-1 switchboard
   * build" sitting beside the original is the single most confusing thing
   * this feature could produce, so the title is the ask - prefilled with
   * "… (copy)" so pressing Enter is still a sensible answer.
   */
  const duplicate = useCallback(
    async (req: WorkRequest) => {
      const r = await qAsk({
        title: t('wr.duplicate_title', { defaultValue: 'Duplicate {{ref}}', ref: req.reference }),
        note: t('wr.duplicate_note', { defaultValue: 'Copies the shape, the typed fields and the estimate - not the hours logged, the history or the conversation. It opens as a draft.' }),
        fields: [{ label: t('wr.title_lbl', { defaultValue: 'Title' }), value: t('wr.copy_of', { defaultValue: '{{title}} (copy)', title: req.title }) }],
        okLabel: t('wr.duplicate', { defaultValue: 'Duplicate' }),
      });
      if (r === null) return;
      const title = r[0]?.trim();
      const copy = await dupM.mutateAsync({ req, title: title || undefined }).catch(() => null);
      // Straight into the new draft: a duplicate nobody opens is a
      // duplicate nobody finishes.
      if (copy) onOpen(copy);
    },
    [dupM, onOpen, t],
  );

  const setTemplate = useCallback(
    async (req: WorkRequest, on: boolean) => {
      const out = await patchM.mutateAsync({ req, patch: { is_template: on } }).catch(() => null);
      if (out !== null) {
        addToast({
          type: 'success',
          title: on
            ? t('wr.templated', { defaultValue: '{{ref}} is now a template', ref: req.reference })
            : t('wr.untemplated', { defaultValue: '{{ref}} is a normal request again', ref: req.reference }),
        });
      }
    },
    [addToast, patchM, t],
  );

  const print = useCallback((req: WorkRequest) => setPrintFor(req), []);

  const assign = useCallback((req: WorkRequest, at: PickAnchor, what: 'assignees' | 'responsible') => setPicker({ req, at, what }), []);
  const handoff = useCallback((req: WorkRequest, department?: string) => setHandoffFor({ req, department }), []);

  const menuFor = useCallback(
    (req: WorkRequest): (MenuItem | null)[] => {
      const dept = deptOf(departments, req.department);
      const closed = isClosed(req.status);
      const items: (MenuItem | null)[] = [
        { label: t('wr.open', { defaultValue: 'Open' }), icon: ExternalLink, onClick: () => onOpen(req) },
        null,
        { label: t('wr.move_to_stage', { defaultValue: 'Move to stage' }), heading: true, onClick: () => undefined },
        ...stagesOf(dept).map<MenuItem>((s) => ({
          label: s.name,
          color: s.colour,
          note: s.key === req.stage ? t('wr.current', { defaultValue: 'current' }) : s.closes ? t('wr.closes', { defaultValue: 'closes' }) : undefined,
          disabled: s.key === req.stage,
          onClick: () => void toStage(req, s.key),
        })),
        null,
        { label: t('wr.assign', { defaultValue: 'Assign' }), heading: true, onClick: () => undefined },
        {
          label: t('wr.assign_people', { defaultValue: 'Assignees…' }),
          icon: Users,
          note: req.assignees.length ? String(req.assignees.length) : undefined,
          onClick: () => assign(req, menu.menu ? { x: menu.menu.x, y: menu.menu.y } : null, 'assignees'),
        },
        {
          label: t('wr.assign_responsible', { defaultValue: 'Responsible…' }),
          icon: Users,
          note: req.responsible?.name,
          onClick: () => assign(req, menu.menu ? { x: menu.menu.x, y: menu.menu.y } : null, 'responsible'),
        },
        null,
        { label: t('wr.needs_info', { defaultValue: 'Needs info…' }), icon: HelpCircle, disabled: closed, onClick: () => void askInfo(req) },
        { label: t('wr.hand_off_to', { defaultValue: 'Hand off to' }), heading: true, onClick: () => undefined },
        ...(departments ?? [])
          .filter((d) => d.active && d.key !== req.department)
          .map<MenuItem>((d) => ({ label: d.name, color: d.colour, icon: ArrowRightLeft, onClick: () => handoff(req, d.key) })),
        null,
        { label: t('wr.log_hours', { defaultValue: 'Log hours…' }), icon: Clock, onClick: () => void logTime(req) },
        { label: t('wr.mark_complete', { defaultValue: 'Mark complete' }), icon: CheckCircle2, disabled: closed, onClick: () => void complete(req) },
        null,
        { label: t('wr.print', { defaultValue: 'Print / Save as PDF' }), icon: Printer, onClick: () => print(req) },
        { label: t('wr.duplicate_menu', { defaultValue: 'Duplicate…' }), icon: CopyPlus, onClick: () => void duplicate(req) },
        {
          label: req.is_template ? t('wr.untemplate', { defaultValue: 'Stop using as a template' }) : t('wr.template', { defaultValue: 'Use as a template' }),
          icon: Star,
          note: req.is_template ? t('wr.is_template', { defaultValue: 'template' }) : undefined,
          onClick: () => void setTemplate(req, !req.is_template),
        },
        null,
        {
          label: t('wr.copy_ref', { defaultValue: 'Copy reference' }),
          icon: Copy,
          note: req.reference,
          onClick: () => {
            void copyText(req.reference).then((ok) =>
              addToast({ type: ok ? 'success' : 'error', title: ok ? t('wr.copied', { defaultValue: 'Copied {{ref}}', ref: req.reference }) : t('wr.copy_failed', { defaultValue: 'Clipboard blocked' }) }),
            );
          },
        },
        {
          label: t('wr.open_job', { defaultValue: 'Open job' }),
          icon: FolderOpen,
          note: req.project_code,
          onClick: () => navigate(`/projects/${encodeURIComponent(req.project_id)}`),
        },
      ];
      return items;
    },
    [addToast, askInfo, assign, complete, departments, duplicate, handoff, logTime, menu.menu, navigate, onOpen, print, setTemplate, t, toStage],
  );

  const openMenu = useCallback(
    (e: React.MouseEvent, req: WorkRequest) => {
      menu.openFromEvent(e, menuFor(req), { head: `${req.reference} · ${req.title}` });
    },
    [menu, menuFor],
  );

  const pickerOptions = useMemo(() => {
    if (!picker) return [];
    const dept = deptOf(departments, picker.req.department);
    const pool = memberPool(dept, users.data ?? []);
    return pool.map((u) => ({ id: u.id, label: u.full_name || u.email, sub: u.email, lead: <Avatar person={{ id: u.id, name: u.full_name || u.email }} size={18} /> }));
  }, [picker, departments, users.data]);

  const element = (
    <>
      {menu.element}
      {picker && (
        <Picker
          anchor={picker.at}
          options={pickerOptions}
          multi={picker.what === 'assignees'}
          selected={picker.what === 'assignees' ? picker.req.assignees.map((a) => a.id) : picker.req.responsible ? [picker.req.responsible.id] : []}
          placeholder={
            picker.what === 'assignees'
              ? t('wr.pick_assignees', { defaultValue: 'Assign people…' })
              : t('wr.pick_responsible', { defaultValue: 'Who is responsible?' })
          }
          onClose={() => setPicker(null)}
          onChange={(ids) => {
            const req = picker.req;
            if (picker.what === 'assignees') void assignM.mutateAsync({ req, ids }).catch(() => undefined);
            else void assignM.mutateAsync({ req, ids: req.assignees.map((a) => a.id), responsible: ids[0] ?? null }).catch(() => undefined);
          }}
        />
      )}
      {logFor && (
        <LogHoursDialog
          req={logFor}
          busy={hoursM.isPending}
          onClose={() => setLogFor(null)}
          onSubmit={async (entry) => {
            const out = await hoursM.mutateAsync({ req: logFor, ...entry }).catch(() => null);
            if (out !== null) setLogFor(null);
          }}
        />
      )}
      {printFor && (
        <RequestPrintSheet req={printFor} departments={departments ?? []} users={users.data ?? []} onDone={() => setPrintFor(null)} />
      )}
      {handoffFor && (
        <HandoffDialog
          req={handoffFor.req}
          departments={departments ?? []}
          initialDepartment={handoffFor.department}
          busy={handoffM.isPending}
          onClose={() => setHandoffFor(null)}
          onSubmit={(body) => void handoffM.mutateAsync({ req: handoffFor.req, body }).catch(() => undefined)}
        />
      )}
    </>
  );

  return {
    menuFor,
    openMenu,
    toStage,
    askInfo,
    logTime,
    complete,
    setStatus,
    toStatusColumn,
    assign,
    handoff,
    duplicate,
    setTemplate,
    print,
    error,
    clearError: () => setError(null),
    element,
  };
}

/* ── Log hours ───────────────────────────────────────────────────── */

export function LogHoursDialog({
  req,
  busy,
  onClose,
  onSubmit,
}: {
  req: WorkRequest;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (entry: { date: string; hours: number; note?: string }) => void;
}) {
  const { t } = useTranslation();
  const [hours, setHours] = useState('');
  const [date, setDate] = useState(() => isoDay(new Date()));
  const [note, setNote] = useState('');
  const [touched, setTouched] = useState(false);

  const n = Number(hours.replace(',', '.'));
  const hoursBad = hours.trim() === '' || !Number.isFinite(n) || n <= 0;
  const valid = !hoursBad && !!date;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="sm"
      testId="wr-loghours"
      title={t('wr.log_hours_title', { defaultValue: 'Log hours on {{ref}}', ref: req.reference })}
      subtitle={req.title}
      footer={
        <div className="wr wr-foot">
          <div className="wr-foot-row">
            <span className="wr-hint wr-foot-draft">
              {t('wr.log_hours_sub', { defaultValue: 'Goes on the request and on its running total.' })}
            </span>
            <div className="wr-foot-acts">
              <button type="button" className="wr-btn-quiet" onClick={onClose} disabled={busy}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                type="button"
                className="wr-btn-quiet on"
                disabled={busy || !valid}
                onClick={() => {
                  setTouched(true);
                  if (!valid) return;
                  onSubmit({ date, hours: n, note: note.trim() || undefined });
                }}
                data-testid="wr-loghours-submit"
              >
                {busy ? t('wr.logging', { defaultValue: 'Logging…' }) : t('wr.log', { defaultValue: 'Log' })}
              </button>
            </div>
          </div>
        </div>
      }
    >
      <div className="wr">
        <div className="wr-form">
          <div className="wr-field">
            <label htmlFor="wr-lh-hours">
              {t('wr.hours', { defaultValue: 'Hours' })} <span className="req">*</span>
            </label>
            <input
              id="wr-lh-hours"
              className={clsx('wr-in', touched && hoursBad && 'miss')}
              inputMode="decimal"
              autoFocus
              value={hours}
              placeholder="4"
              list="wr-lh-common"
              onChange={(e) => setHours(e.target.value.replace(/[^\d.,]/g, ''))}
            />
            <datalist id="wr-lh-common">
              {['1', '2', '4', '8'].map((h) => (
                <option key={h} value={h} />
              ))}
            </datalist>
            {touched && hoursBad && <span className="err">{t('wr.hours_bad', { defaultValue: 'Hours must be a number above zero.' })}</span>}
          </div>
          <div className="wr-field">
            <label htmlFor="wr-lh-date">
              {t('wr.date', { defaultValue: 'Date' })} <span className="req">*</span>
            </label>
            {/* The browser's own picker, in the reader's own format - the
                same control every other date in the module uses. */}
            <input id="wr-lh-date" type="date" className="wr-in" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div className="wr-field wide">
            <label htmlFor="wr-lh-note">{t('wr.note_opt', { defaultValue: 'Note (optional)' })}</label>
            <input
              id="wr-lh-note"
              className="wr-in"
              value={note}
              placeholder={t('wr.log_note_ph', { defaultValue: 'what was done' })}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && valid) onSubmit({ date, hours: n, note: note.trim() || undefined });
              }}
            />
          </div>
        </div>
      </div>
    </WideModal>
  );
}

/* ── Hand off to another department ──────────────────────────────── */

export function HandoffDialog({
  req,
  departments,
  initialDepartment,
  busy,
  onClose,
  onSubmit,
}: {
  req: WorkRequest;
  departments: Department[];
  initialDepartment?: string;
  busy?: boolean;
  onClose: () => void;
  onSubmit: (body: HandoffBody) => void;
}) {
  const { t } = useTranslation();
  const others = departments.filter((d) => d.active && d.key !== req.department);
  const [dept, setDept] = useState<string>(initialDepartment ?? others[0]?.key ?? '');
  const target = departments.find((d) => d.key === dept);
  const offered = typesOf(target);
  // Multi, like the raise dialog: a handoff is a new request, and a new
  // request can be several types at once.
  const [types, setTypes] = useState<string[]>(offered[0] ? [offered[0].key] : []);
  const [title, setTitle] = useState(req.title);
  const [description, setDescription] = useState('');
  const [due, setDue] = useState(req.due_date ?? '');
  const [infoBy, setInfoBy] = useState('');
  const [copyLinks, setCopyLinks] = useState(true);
  const [touched, setTouched] = useState(false);

  const pickDept = (key: string) => {
    setDept(key);
    const first = typesOf(departments.find((x) => x.key === key))[0];
    setTypes(first ? [first.key] : []);
  };

  const valid = !!dept && types.length > 0 && title.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      busy={busy}
      size="md"
      title={t('wr.handoff_title', { defaultValue: 'Hand off {{ref}} to another department', ref: req.reference })}
      subtitle={t('wr.handoff_sub', { defaultValue: 'Raises a child request on the same job, linked both ways.' })}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" className="wr-btn-quiet" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="button"
            className="wr-btn-quiet on"
            disabled={busy || !valid}
            onClick={() => {
              setTouched(true);
              if (!valid) return;
              onSubmit({
                department: dept,
                request_type: types[0] ?? '',
                request_types: types,
                title: title.trim(),
                description: description.trim() || undefined,
                due_date: due || null,
                info_required_by: infoBy || null,
                copy_links: copyLinks,
              });
            }}
          >
            {busy ? t('wr.handing_off', { defaultValue: 'Handing off…' }) : t('wr.hand_off', { defaultValue: 'Hand off' })}
          </button>
        </div>
      }
    >
      <div className="wr">
        {others.length === 0 ? (
          <div className="wr-empty">{t('wr.handoff_none', { defaultValue: 'There is no other active department to hand this to.' })}</div>
        ) : (
          <div className="flex flex-col gap-4">
            <div>
              <div className="wr-lab mb-2">{t('wr.department', { defaultValue: 'Department' })}</div>
              <div className="wr-deptcards">
                {others.map((d) => (
                  <button key={d.key} type="button" className="wr-deptcard" aria-pressed={dept === d.key} style={{ ['--dc' as string]: resolveColour(d.colour) }} onClick={() => pickDept(d.key)}>
                    <b>{d.name}</b>
                    {d.description && <span>{d.description}</span>}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="wr-lab mb-2">
                {t('wr.request_types', { defaultValue: 'Request types' })}
                {touched && types.length === 0 && (
                  <span className="err ml-2 normal-case tracking-normal">{t('wr.err_type', { defaultValue: 'Pick at least one request type.' })}</span>
                )}
              </div>
              <div className="wr-typechips" role="group" aria-label={t('wr.request_types', { defaultValue: 'Request types' })}>
                {offered.map((rt) => (
                  <button
                    key={rt.key}
                    type="button"
                    className="wr-typechip"
                    aria-pressed={types.includes(rt.key)}
                    onClick={() => setTypes((k) => (k.includes(rt.key) ? k.filter((x) => x !== rt.key) : [...k, rt.key]))}
                  >
                    <span className="tick" aria-hidden>
                      {types.includes(rt.key) ? '✓' : '+'}
                    </span>
                    {rt.label}
                  </button>
                ))}
                {target && offered.length === 0 && <span className="wr-hint">{t('wr.no_types', { defaultValue: 'This department has no request types configured.' })}</span>}
              </div>
            </div>
            <div className="wr-form">
              <div className="wr-field wide">
                <label htmlFor="wr-ho-title">
                  {t('wr.title_lbl', { defaultValue: 'Title' })} <span className="req">*</span>
                </label>
                <input id="wr-ho-title" className={`wr-in${touched && !title.trim() ? ' miss' : ''}`} value={title} onChange={(e) => setTitle(e.target.value)} />
              </div>
              <div className="wr-field wide">
                <label htmlFor="wr-ho-desc">{t('wr.description', { defaultValue: 'Description' })}</label>
                <textarea id="wr-ho-desc" className="wr-in" value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('wr.handoff_desc_ph', { defaultValue: 'What the other department needs to know' })} />
              </div>
              <div className="wr-field">
                <label htmlFor="wr-ho-info">{t('wr.info_by', { defaultValue: 'Info required by' })}</label>
                <input id="wr-ho-info" type="date" className="wr-in" value={infoBy} onChange={(e) => setInfoBy(e.target.value)} />
              </div>
              <div className="wr-field">
                <label htmlFor="wr-ho-due">{t('wr.due', { defaultValue: 'Due' })}</label>
                <input id="wr-ho-due" type="date" className="wr-in" value={due} onChange={(e) => setDue(e.target.value)} />
              </div>
              <label className="wr-tog wide" style={{ gridColumn: '1 / -1' }}>
                <input type="checkbox" checked={copyLinks} onChange={(e) => setCopyLinks(e.target.checked)} />
                {t('wr.copy_links', { defaultValue: 'Copy the links across' })}
              </label>
            </div>
          </div>
        )}
      </div>
    </WideModal>
  );
}
