// Design module (ERP side of the design editor link).
/**
 * Design → Brief: the typed form that produces `ddc-brief/1` for the active project, with the
 * plot drawn on a map. Every value shows its provenance; a person confirms values one by one or
 * all at once. Saving creates a new brief version on the server.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { CheckCheck, FolderOpen, PencilRuler, Plus, Save } from 'lucide-react';
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton } from '@/shared/ui';
import { fetchDocuments } from '@/features/documents/api';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { confirmBrief, fetchBrief, saveBrief } from './api';
import {
  SECTIONS,
  SPACE_FIELDS,
  UNIT_FIELDS,
  addItem,
  briefErrors,
  citeDocument,
  documentCitations,
  editField,
  errorsAt,
  getAt,
  newBrief,
  removeItem,
  roomKinds,
  serverErrors,
  tidy,
  unconfirmed,
  type BriefDoc,
  type ErrorMap,
} from './data/briefModel';
import { Field, RemoveButton, fieldLabel, tr, type ProvenanceProps } from './BriefFields';
import { useLeaveGuard } from './useLeaveGuard';
import { PlotEditor } from './PlotEditor';
import { CiteDialog } from './CiteDialog';

const KINDS = roomKinds();

/** A person's wording for why a call failed: signed out, server unreachable, or the server's own text. */
function problemText(t: Parameters<typeof tr>[0], err: unknown): string {
  if (err instanceof ApiError && err.status === 401) return tr(t, 'design.brief.session_expired');
  if (err instanceof TypeError || (err instanceof ApiError && err.status === 0)) return tr(t, 'design.brief.unreachable');
  return getErrorMessage(err);
}
const SERVER_OWNED = new Set(['/schema', '/brief_id', '/project_id', '/version']);

export default function BriefPage() {
  const { t } = useTranslation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  if (!projectId) {
    return (
      <EmptyState
        icon={<FolderOpen size={28} aria-hidden />}
        title={tr(t, 'design.brief.no_project')}
        description={tr(t, 'design.brief.no_project_hint')}
      />
    );
  }
  return <BriefEditor key={projectId} projectId={projectId} />;
}

function BriefEditor({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const project = useQuery({ queryKey: ['projects', projectId], queryFn: () => projectsApi.get(projectId) });
  const brief = useQuery({ queryKey: ['design-brief', projectId], queryFn: () => fetchBrief(projectId) });

  const [doc, setDoc] = useState<BriefDoc | null>(null);
  const [baseVersion, setBaseVersion] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [remoteErrors, setRemoteErrors] = useState<ErrorMap>({});
  const [conflict, setConflict] = useState<'changed' | 'version' | null>(null);
  const [unreadable, setUnreadable] = useState<ReadonlySet<string>>(new Set());
  const [epoch, setEpoch] = useState(0);
  const [citing, setCiting] = useState<string | null>(null);

  // Adopt the loaded brief, or start a new one from the project settings.
  useEffect(() => {
    if (doc || !brief.isSuccess || !project.isSuccess) return;
    if (brief.data) {
      setDoc(brief.data);
      setBaseVersion(brief.data.version);
    } else {
      const p = project.data;
      setDoc(newBrief({ id: projectId, country_code: p.country_code, locale: p.locale, currency: p.currency, name: p.name },
        crypto.randomUUID()));
      setBaseVersion(0);
    }
  }, [brief.isSuccess, brief.data, project.isSuccess, project.data, doc, projectId]);

  const errors = useMemo(() => {
    if (!doc) return {};
    // The server assigns ids, schema and version on every save; they are not the person's to fix.
    const own = Object.fromEntries(Object.entries(briefErrors(doc)).filter(([p]) => !SERVER_OWNED.has(p)));
    return { ...own, ...remoteErrors };
  }, [doc, remoteErrors]);
  // A missing required value does not block a draft; any other problem (and any unreadable entry) does.
  const missing = useMemo(
    () => Object.values(errors).flat().filter((e) => e.code === 'required').length,
    [errors],
  );
  const errorCount = Object.values(errors).flat().length - missing + unreadable.size;
  const open = useMemo(() => (doc ? unconfirmed(doc) : []), [doc]);

  const markUnreadable = useCallback((pointer: string, bad: boolean) => {
    setUnreadable((cur) => {
      if (cur.has(pointer) === bad) return cur;
      const next = new Set(cur);
      if (bad) next.add(pointer);
      else next.delete(pointer);
      return next;
    });
  }, []);

  useLeaveGuard(dirty, tr(t, 'design.brief.leave_confirm'));

  const change = useCallback((pointer: string, value: unknown) => {
    setDoc((d) => (d ? editField(d, pointer, value, pointer === '/site/plot' ? 'map' : 'user') : d));
    setDirty(true);
    setRemoteErrors((r) => Object.fromEntries(Object.entries(r).filter(([p]) => !p.startsWith(pointer))));
  }, []);

  const adopt = (saved: BriefDoc) => {
    setDoc(saved);
    setBaseVersion(saved.version);
    setDirty(false);
    setRemoteErrors({});
    setConflict(null);
    queryClient.setQueryData(['design-brief', projectId], saved);
  };

  const failed = (err: unknown, titleKey: string) => {
    const status = err instanceof ApiError ? err.status : 0;
    if (status === 409) setConflict('changed');
    if (status === 428) setConflict('version');
    if (status === 422) setRemoteErrors(serverErrors((err as ApiError).body));
    const message =
      status === 409 ? tr(t, 'design.brief.conflict')
      : status === 428 ? tr(t, 'design.brief.precondition')
      : status === 426 ? tr(t, 'design.brief.version_unsupported')
      : problemText(t, err);
    addToast({ type: 'error', title: tr(t, titleKey), message });
  };

  const save = async () => {
    if (!doc) return;
    setBusy(true);
    try {
      const saved = await saveBrief(projectId, tidy(doc), baseVersion, missing > 0);
      adopt(saved);
      addToast({
        type: 'success',
        title: tr(t, missing > 0 ? 'design.brief.saved_incomplete' : 'design.brief.saved', { version: saved.version, count: missing }),
      });
    } catch (err) {
      failed(err, 'design.brief.save_failed');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (pointers: string[]) => {
    if (!pointers.length) return;
    setBusy(true);
    try {
      adopt(await confirmBrief(projectId, pointers, baseVersion));
      addToast({ type: 'success', title: tr(t, 'design.brief.confirmed_n', { count: pointers.length }) });
    } catch (err) {
      failed(err, 'design.brief.confirm_failed');
    } finally {
      setBusy(false);
    }
  };

  const reload = async () => {
    // Take the answer of this fetch, not the cached query data: that is still the old version.
    const fresh = await brief.refetch();
    if (fresh.isError) return;
    setUnreadable(new Set());
    setEpoch((n) => n + 1);
    if (fresh.data) adopt(fresh.data);
    else {
      setDoc(null); // deleted meanwhile: start a new brief from the project
      setDirty(false);
      setConflict(null);
      setRemoteErrors({});
    }
  };

  if (project.isError || brief.isError) {
    return (
      <ErrorState
        title={tr(t, 'design.brief.load_failed')}
        hint={problemText(t, project.error ?? brief.error)}
        onRetry={() => { void project.refetch(); void brief.refetch(); }}
      />
    );
  }
  if (!doc) return <Skeleton className="h-96 w-full" />;

  const canConfirm = baseVersion > 0 && !dirty && !busy;
  const provenance: Omit<ProvenanceProps, 'doc' | 'pointer'> = {
    onConfirm: canConfirm ? (p: string) => void confirm([p]) : null,
    confirmBlockedReason: tr(t, 'design.brief.save_first'),
    onCite: (p: string) => setCiting(p),
  };
  const fieldProps = { doc, onChange: change, onParseError: markUnreadable, provenance, currency: getAt(doc, '/budget/currency') as string | undefined };
  const addr = project.data?.address;
  const focus = addr?.lat != null && addr?.lng != null ? { lat: addr.lat, lng: addr.lng } : null;

  return (
    <div className="space-y-5 pb-16" key={epoch}>
      <h1 className="text-xl font-semibold text-content-primary">{tr(t, 'design.brief.title')}</h1>
      <PageHeader
        subtitle={tr(t, 'design.brief.subtitle')}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={baseVersion ? 'neutral' : 'blue'}>
              {baseVersion ? tr(t, 'design.brief.version', { version: baseVersion }) : tr(t, 'design.brief.new')}
            </Badge>
            {dirty && <Badge variant="warning">{tr(t, 'design.brief.unsaved')}</Badge>}
            {missing > 0 && <Badge variant="warning">{tr(t, 'design.brief.incomplete', { count: missing })}</Badge>}
            <Button
              variant="secondary"
              disabled={!canConfirm || !open.length}
              title={canConfirm ? undefined : tr(t, 'design.brief.save_first')}
              onClick={() => void confirm(open)}
            >
              <CheckCheck size={16} aria-hidden />
              {open.length ? tr(t, 'design.brief.confirm_all', { count: open.length }) : tr(t, 'design.brief.all_confirmed')}
            </Button>
            <Button
              onClick={() => void save()}
              disabled={busy || (!dirty && baseVersion > 0) || errorCount > 0}
              title={errorCount ? tr(t, 'design.brief.fix_errors', { count: errorCount }) : undefined}
            >
              <Save size={16} aria-hidden />
              {tr(t, 'design.brief.save')}
            </Button>
          </div>
        }
      />

      {conflict && (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-semantic-warning bg-semantic-warning-bg p-3 text-sm">
          <span>{tr(t, conflict === 'version' ? 'design.brief.precondition' : 'design.brief.conflict')}</span>
          <Button size="sm" variant="secondary" onClick={() => void reload()}>{tr(t, 'design.brief.reload')}</Button>
        </div>
      )}
      {errorCount > 0 && (
        <p className="text-sm text-semantic-error">{tr(t, 'design.brief.fix_errors', { count: errorCount })}</p>
      )}
      {baseVersion > 0 && !dirty && errorCount === 0 && (
        <p data-testid="brief-next" className="flex flex-wrap items-center gap-2 text-sm text-content-secondary">
          <PencilRuler size={14} aria-hidden />
          {tr(t, 'design.brief.next_editor')}
          <Link className="text-oe-blue-text underline" to="/design/editor">{tr(t, 'design.editor.open')}</Link>
        </p>
      )}

      <Questions doc={doc} />
      <SourceDocuments projectId={projectId} doc={doc} />
      <CiteDialog
        projectId={projectId}
        pointer={citing}
        onClose={() => setCiting(null)}
        onCite={(p, source) => { setDoc((d) => (d ? citeDocument(d, p, source) : d)); setDirty(true); }}
      />

      <div className="grid gap-5 xl:grid-cols-2">
        {SECTIONS.filter((s) => s.id !== 'programme').map((section) => (
          <Card key={section.id} data-section={section.id}>
            <CardHeader title={tr(t, `design.section.${section.id}`)} />
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {section.fields.map((p) => (
                <Field key={p} pointer={p} errors={errorsAt(errors, p)} {...fieldProps} />
              ))}
            </div>
          </Card>
        ))}
      </div>

      <Card data-section="plot">
        <CardHeader title={tr(t, 'design.plot.title')} />
        <div className="mt-4">
          <PlotEditor doc={doc} errors={errorsAt(errors, '/site/plot')} focus={focus} onChange={change} provenance={provenance} />
        </div>
      </Card>

      <Card data-section="programme">
        <CardHeader title={tr(t, 'design.section.programme')} />
        <div className="mt-4 space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field pointer="/programme/parking_spaces" errors={errorsAt(errors, '/programme/parking_spaces')} {...fieldProps} />
          </div>
          <Units doc={doc} errors={errors} fieldProps={fieldProps} onDoc={(d) => { setDoc(d); setDirty(true); }} />
          <Spaces doc={doc} errors={errors} fieldProps={fieldProps} onDoc={(d) => { setDoc(d); setDirty(true); }} />
        </div>
      </Card>
    </div>
  );
}

type FieldShared = Omit<Parameters<typeof Field>[0], 'pointer' | 'errors'>;

interface ListProps {
  doc: BriefDoc;
  errors: ErrorMap;
  fieldProps: FieldShared;
  onDoc: (doc: BriefDoc) => void;
}

function Units({ doc, errors, fieldProps, onDoc }: ListProps) {
  const { t } = useTranslation();
  const units = (getAt(doc, '/programme/units') as unknown[] | undefined) ?? [];
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-content-primary">{tr(t, 'design.brief.units')}</h3>
      {units.map((_, i) => {
        const base = `/programme/units/${i}`;
        const rooms = (getAt(doc, `${base}/rooms`) as unknown[] | undefined) ?? [];
        return (
          <div key={i} className="space-y-3 rounded-lg border border-border-light p-4" data-testid={`unit-${i}`}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{tr(t, 'design.brief.unit_n', { n: i + 1 })}</span>
              <RemoveButton label={tr(t, 'design.brief.remove')} onClick={() => onDoc(removeItem(doc, '/programme/units', i))} />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {UNIT_FIELDS.map((f) => (
                <Field key={f} pointer={`${base}/${f}`} errors={errorsAt(errors, `${base}/${f}`)} {...fieldProps} />
              ))}
            </div>
            <div className="space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {tr(t, 'design.brief.rooms')}
              </span>
              {(errors[`${base}/rooms`] ?? []).map((e) => (
                <p key={e.code} role="alert" className="text-xs text-semantic-error">{fieldLabel(t, `${base}/rooms/0/kind`)}: {tr(t, `design.error.${e.code}`, { param: e.param })}</p>
              ))}
              {rooms.map((__, j) => (
                <SpaceRow key={j} base={`${base}/rooms/${j}`} errors={errors} fieldProps={fieldProps}
                  onRemove={() => onDoc(removeItem(doc, `${base}/rooms`, j))} />
              ))}
              <Button size="sm" variant="ghost" onClick={() => onDoc(addItem(doc, `${base}/rooms`, { kind: '' }))}>
                <Plus size={14} aria-hidden /> {tr(t, 'design.brief.add_room')}
              </Button>
            </div>
          </div>
        );
      })}
      <Button size="sm" variant="secondary"
        onClick={() => onDoc(addItem(doc, '/programme/units', { name: '', count: 1, rooms: [{ kind: '' }] }))}>
        <Plus size={14} aria-hidden /> {tr(t, 'design.brief.add_unit')}
      </Button>
    </section>
  );
}

function Spaces({ doc, errors, fieldProps, onDoc }: ListProps) {
  const { t } = useTranslation();
  const spaces = (getAt(doc, '/programme/spaces') as unknown[] | undefined) ?? [];
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-content-primary">{tr(t, 'design.brief.spaces')}</h3>
      {spaces.map((_, i) => (
        <SpaceRow key={i} base={`/programme/spaces/${i}`} errors={errors} fieldProps={fieldProps}
          onRemove={() => onDoc(removeItem(doc, '/programme/spaces', i))} />
      ))}
      <Button size="sm" variant="secondary" onClick={() => onDoc(addItem(doc, '/programme/spaces', { kind: '' }))}>
        <Plus size={14} aria-hidden /> {tr(t, 'design.brief.add_space')}
      </Button>
    </section>
  );
}

function SpaceRow({ base, errors, fieldProps, onRemove }: {
  base: string;
  errors: ErrorMap;
  fieldProps: FieldShared;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid items-start gap-3 rounded-lg bg-surface-secondary p-3 sm:grid-cols-[repeat(6,minmax(0,1fr))_auto]">
      {SPACE_FIELDS.map((f) => (
        <Field key={f} compact pointer={`${base}/${f}`} errors={errorsAt(errors, `${base}/${f}`)}
          suggestions={f === 'kind' ? KINDS : undefined} {...fieldProps} />
      ))}
      <div className="self-end">
        <RemoveButton label={tr(t, 'design.brief.remove')} onClick={onRemove} />
      </div>
    </div>
  );
}

function Questions({ doc }: { doc: BriefDoc }) {
  const { t } = useTranslation();
  const questions = doc.questions ?? [];
  if (!questions.length) return null;
  return (
    <Card data-section="questions">
      <CardHeader title={tr(t, 'design.brief.questions')} />
      <ul className="mt-3 space-y-2 text-sm">
        {questions.map((q) => (
          <li key={q.id} className="flex flex-col">
            <span className="text-content-primary">{q.text}</span>
            <span className="text-xs text-content-tertiary">
              {tr(t, 'design.brief.question_about', { field: safeLabel(t, q.pointer) })}
              {q.options.length ? ` · ${q.options.join(' / ')}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function safeLabel(t: Parameters<typeof fieldLabel>[0], pointer: string): string {
  try {
    return fieldLabel(t, pointer);
  } catch {
    return pointer;
  }
}

/** Project documents the brief cites, with how many values rest on each. */
function SourceDocuments({ projectId, doc }: { projectId: string; doc: BriefDoc }) {
  const { t } = useTranslation();
  const counts = useMemo(() => documentCitations(doc), [doc]);
  const ids = Object.keys(counts);
  const docs = useQuery({
    queryKey: ['design-brief-documents', projectId],
    queryFn: () => fetchDocuments(projectId, { limit: 100 }),
    enabled: ids.length > 0,
  });
  if (!ids.length) return null;
  const names = new Map((docs.data?.items ?? []).map((d) => [d.id, d.name]));
  return (
    <Card data-section="documents">
      <CardHeader title={tr(t, 'design.cite.cited_documents')} />
      <ul className="mt-3 space-y-1 text-sm">
        {ids.map((id) => (
          <li key={id} className="flex items-center justify-between gap-3">
            <span className="truncate">{names.get(id) ?? tr(t, 'design.cite.unknown_document')}</span>
            <Badge variant="neutral" size="sm">{tr(t, 'design.cite.values_n', { count: counts[id] })}</Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}
