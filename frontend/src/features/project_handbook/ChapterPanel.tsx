// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One chapter of the handbook: its text, owner, version and approval, the
// records of other modules it reads live, and the approved versions. Which
// buttons exist follows the capability flags the server sent with the chapter.

import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, ExternalLink, Save, Send, Undo2 } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { fmtDate } from '@/shared/lib/formatters';

import {
  approveChapter,
  patchChapter,
  returnChapter,
  submitChapter,
  type Can,
  type ChapterDetail,
  type ChapterVersion,
  type LinkedSource,
} from './api';
import { OwnerControl } from './OwnerControl';
import { useChapter, useHandbookAction } from './hooks';
import {
  CHAPTER_STATUS,
  CHAPTER_TONE,
  chapterTitle,
  keyText,
  linkedLabel,
  refusalText,
  sourceTitle,
  type TFn,
} from './labels';

const FIELD_CLASS =
  'w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-60';

function ActionButton({
  can,
  label,
  icon,
  variant,
  busy,
  onClick,
  testId,
}: {
  can: Can | undefined;
  label: string;
  icon: ReactNode;
  variant: 'primary' | 'secondary';
  busy: boolean;
  onClick: () => void;
  testId: string;
}) {
  const { t } = useTranslation();
  // An action that does not fit the state at all is left off; one that is only refused for this caller shows why.
  if (!can || can.applies === false) return null;
  return (
    <Button
      variant={variant}
      size="sm"
      icon={icon}
      loading={busy}
      disabled={!can.allowed}
      title={
        !can.allowed && can.reason
          ? t(`project_handbook.errors.${can.reason}`, { defaultValue: can.reason.replace(/_/g, ' ') })
          : undefined
      }
      onClick={onClick}
      data-testid={testId}
    >
      {label}
    </Button>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-content-tertiary">{label}</dt>
      <dd className="text-sm text-content-primary">{children || '-'}</dd>
    </div>
  );
}

function LinkedSourceBlock({ source, projectId }: { source: LinkedSource; projectId: string }) {
  const { t } = useTranslation();
  const tf = t as TFn;
  const grouped = new Map<string, typeof source.rows>();
  for (const row of source.rows) {
    const list = grouped.get(row.group) ?? [];
    list.push(row);
    grouped.set(row.group, list);
  }
  return (
    <section className="rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid={`handbook-source-${source.source}`}>
      <header className="flex items-center justify-between gap-2 border-b border-border-light px-3 py-2">
        <h4 className="text-sm font-medium text-content-primary">
          {sourceTitle(tf, source.source)}
          <span className="ml-2 text-xs font-normal text-content-tertiary">{source.rows.length}</span>
        </h4>
        <Link
          to={source.route.replace('{project_id}', projectId)}
          className="inline-flex items-center gap-1 text-xs text-oe-blue hover:underline"
        >
          {t('projectHandbook.open_module', { defaultValue: 'Open' })}
          <ExternalLink size={12} aria-hidden />
        </Link>
      </header>
      {source.rows.length === 0 ? (
        <p className="px-3 py-3 text-sm text-content-secondary">
          {t('projectHandbook.source_empty', { defaultValue: 'No records in the project yet.' })}
        </p>
      ) : (
        <div className="divide-y divide-border-light">
          {[...grouped.entries()].map(([group, rows]) => (
            <div key={group || 'rows'}>
              {group ? (
                <p className="bg-surface-secondary px-3 py-1 text-xs font-medium uppercase tracking-wide text-content-tertiary">
                  {group}
                </p>
              ) : null}
              <ul className="divide-y divide-border-light">
                {rows.map((row, i) => (
                  <li key={`${row.label}:${i}`} className="flex items-baseline justify-between gap-3 px-3 py-1.5 text-sm">
                    <span className="text-content-primary">{linkedLabel(tf, row)}</span>
                    <span className="shrink-0 text-xs text-content-secondary">{row.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function VersionRow({ version }: { version: ChapterVersion }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-md border border-border bg-surface-elevated" data-testid={`handbook-version-${version.version}`}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="font-medium text-content-primary">
          {t('projectHandbook.version_n', { defaultValue: 'Version {{n}}', n: version.version })}
        </span>
        <span className="text-xs text-content-secondary">
          {version.approved_by_name || '-'}, {fmtDate(version.approved_at)}
        </span>
      </button>
      {open ? (
        <p className="whitespace-pre-wrap border-t border-border-light px-3 py-2 text-sm text-content-secondary">
          {version.content}
        </p>
      ) : null}
    </li>
  );
}

export function ChapterPanel({
  projectId,
  code,
  onChanged,
}: {
  projectId: string;
  code: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const tf = t as TFn;
  const query = useChapter(projectId, code);
  const chapter = query.data;
  const [text, setText] = useState('');
  const [loadedKey, setLoadedKey] = useState('');

  // Take the server's text whenever another chapter, or a new state of this one, arrives.
  const key = chapter ? `${chapter.code}:${chapter.status}:${chapter.draft_version}:${chapter.content.length}` : '';
  useEffect(() => {
    if (chapter && key !== loadedKey) {
      setText(chapter.content);
      setLoadedKey(key);
    }
  }, [chapter, key, loadedKey]);

  const done = (next?: ChapterDetail) => {
    if (next) setText(next.content);
    onChanged();
    void query.refetch();
  };
  const save = useHandbookAction((content: string) => patchChapter(projectId, code, { content }), done);
  const submit = useHandbookAction(() => submitChapter(projectId, code), done);
  const back = useHandbookAction(() => returnChapter(projectId, code), done);
  const approve = useHandbookAction(() => approveChapter(projectId, code), done);

  if (query.isLoading) return <SkeletonTable rows={6} columns={2} />;
  if (query.isError || !chapter) {
    return (
      <ErrorState
        title={t('projectHandbook.chapter_load_failed', { defaultValue: 'The chapter could not be loaded' })}
        hint={refusalText(tf, query.error)}
        onRetry={() => query.refetch()}
      />
    );
  }

  const can = chapter.can;
  const editable = !!can?.edit.allowed;
  const dirty = text !== chapter.content;
  const status = chapter.status;
  return (
    <div className="space-y-4" data-testid="handbook-chapter">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-content-primary">{chapterTitle(tf, chapter)}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Badge variant={CHAPTER_TONE[status]} dot>
              {keyText(tf, CHAPTER_STATUS[status])}
            </Badge>
            {chapter.required ? (
              <Badge variant="blue">{t('projectHandbook.required', { defaultValue: 'Required for the gate' })}</Badge>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton
            can={can?.edit}
            label={t('projectHandbook.save', { defaultValue: 'Save' })}
            icon={<Save size={14} />}
            variant="secondary"
            busy={save.isPending}
            onClick={() => save.mutate(text)}
            testId="handbook-save"
          />
          <ActionButton
            can={can?.submit}
            label={t('projectHandbook.submit', { defaultValue: 'Submit for approval' })}
            icon={<Send size={14} />}
            variant="primary"
            busy={submit.isPending}
            onClick={() => (dirty ? save.mutateAsync(text).then(() => submit.mutate()) : submit.mutate())}
            testId="handbook-submit"
          />
          <ActionButton
            can={can?.return}
            label={t('projectHandbook.return', { defaultValue: 'Return' })}
            icon={<Undo2 size={14} />}
            variant="secondary"
            busy={back.isPending}
            onClick={() => back.mutate()}
            testId="handbook-return"
          />
          <ActionButton
            can={can?.approve}
            label={t('projectHandbook.approve', { defaultValue: 'Approve' })}
            icon={<CheckCircle2 size={14} />}
            variant="primary"
            busy={approve.isPending}
            onClick={() => approve.mutate()}
            testId="handbook-approve"
          />
        </div>
      </header>

      <dl className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface-elevated shadow-sm px-4 py-3 md:grid-cols-4">
        <Fact label={t('projectHandbook.owner', { defaultValue: 'Owner' })}>
          <OwnerControl projectId={projectId} chapter={chapter} canChange={editable} onChanged={done} />
        </Fact>
        <Fact label={t('projectHandbook.working_version', { defaultValue: 'Working version' })}>
          {chapter.draft_version}
        </Fact>
        <Fact label={t('projectHandbook.approved_version', { defaultValue: 'Approved version' })}>
          {chapter.approved_version ?? ''}
        </Fact>
        <Fact label={t('projectHandbook.approved_by', { defaultValue: 'Approved by' })}>
          {chapter.approved_by_name
            ? `${chapter.approved_by_name}${chapter.approved_at ? `, ${fmtDate(chapter.approved_at)}` : ''}`
            : ''}
        </Fact>
      </dl>
      {status === 'in_review' && chapter.submitted_by_name ? (
        <p className="text-sm text-content-secondary" data-testid="handbook-review-note">
          {t('projectHandbook.submitted_by_note', {
            defaultValue: 'Submitted by {{name}} on {{date}}. With four eyes, someone else approves.',
            name: chapter.submitted_by_name,
            date: chapter.submitted_at ? fmtDate(chapter.submitted_at) : '',
          })}
        </p>
      ) : null}

      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">
          {t('projectHandbook.text', { defaultValue: 'Text' })}
        </span>
        <textarea
          className={FIELD_CLASS}
          rows={12}
          value={text}
          maxLength={200000}
          disabled={!editable}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('projectHandbook.text_placeholder', { defaultValue: 'Write what the team needs to know and follow.' })}
          data-testid="handbook-text"
        />
      </label>
      {!editable && can?.edit.reason ? (
        <p className="text-xs text-content-secondary">
          {t(`project_handbook.errors.${can.edit.reason}`, { defaultValue: can.edit.reason.replace(/_/g, ' ') })}
        </p>
      ) : null}
      {chapter.linked.length > 0 ? (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('projectHandbook.live_records', { defaultValue: 'Live from the project' })}
          </h3>
          <p className="text-xs text-content-secondary">
            {t('projectHandbook.live_records_hint', {
              defaultValue: 'These records are read from the modules they live in at the moment you open or print the handbook. They are not copied into the chapter.',
            })}
          </p>
          {chapter.linked.map((source) => (
            <LinkedSourceBlock key={source.source} source={source} projectId={projectId} />
          ))}
        </div>
      ) : null}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('projectHandbook.versions', { defaultValue: 'Approved versions' })}
        </h3>
        {chapter.versions.length === 0 ? (
          <p className="text-sm text-content-secondary">
            {t('projectHandbook.no_versions', { defaultValue: 'Nothing approved yet.' })}
          </p>
        ) : (
          <ul className="space-y-2">
            {chapter.versions.map((v) => (
              <VersionRow key={v.version} version={v} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
