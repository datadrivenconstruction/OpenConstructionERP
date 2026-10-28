// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The project handbook, mounted at /projects/:projectId/handbook.
//
// The head shows how many chapters are approved and how many required ones
// still block the gate, with the download of the whole handbook as a PDF.
// Two tabs (?tab=): the chapters, a list on the left and the open chapter on
// the right (?chapter=), and the data room. Buttons follow the capability
// flags the server sent with every chapter.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useProjectName } from '@/shared/hooks/useProjectName';
import { useParams, useSearchParams } from 'react-router-dom';
import { AlertTriangle, BookOpen, Download, FolderTree, Star } from 'lucide-react';

import { Badge } from '@/shared/ui/Badge';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { TabBar } from '@/shared/ui/TabBar';

import { createHandbook, downloadHandbook, type Chapter, type Finding, type Handbook } from './api';
import { ChapterPanel } from './ChapterPanel';
import { DataRoomTab } from './DataRoomTab';
import { useFindings, useHandbook, useHandbookAction, useInvalidateHandbook } from './hooks';
import { CHAPTER_STATUS, CHAPTER_TONE, chapterTitle, findingText, keyText, refusalText, type TFn } from './labels';

type Tab = 'chapters' | 'data_room';
const TABS: Tab[] = ['chapters', 'data_room'];

function ChapterList({ chapters, active, onPick }: { chapters: Chapter[]; active: string; onPick: (code: string) => void }) {
  const { t } = useTranslation();
  const tf = t as TFn;
  return (
    <ol className="divide-y divide-border-light overflow-hidden rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid="handbook-chapter-list">
      {chapters.map((c, i) => (
        <li key={c.code}>
          <button
            type="button"
            onClick={() => onPick(c.code)}
            aria-current={c.code === active ? 'true' : undefined}
            className={`flex w-full items-start gap-3 px-3 py-2.5 text-left hover:bg-surface-secondary ${c.code === active ? 'bg-surface-secondary' : ''}`}
            data-testid={`handbook-chapter-${c.code}`}
          >
            <span className="mt-0.5 w-6 shrink-0 text-right text-xs tabular-nums text-content-tertiary">{i + 1}</span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
                <span className="truncate">{chapterTitle(tf, c)}</span>
                {c.required ? (
                  <Star
                    size={12}
                    className="shrink-0 text-semantic-warning"
                    aria-label={t('projectHandbook.required', { defaultValue: 'Required for the gate' })}
                  />
                ) : null}
              </span>
              <span className="mt-0.5 block truncate text-xs text-content-secondary">
                {c.owner_name || t('projectHandbook.no_owner', { defaultValue: 'No owner yet' })}
                {c.approved_version !== null
                  ? ` · ${t('projectHandbook.version_short', { defaultValue: 'v{{n}}', n: c.approved_version })}`
                  : ''}
              </span>
            </span>
            <Badge variant={CHAPTER_TONE[c.status]} size="sm">
              {keyText(tf, CHAPTER_STATUS[c.status])}
            </Badge>
          </button>
        </li>
      ))}
    </ol>
  );
}

function Head({ handbook, findings }: { handbook: Handbook; findings: Finding[] }) {
  const { t } = useTranslation();
  const tf = t as TFn;
  const download = useHandbookAction(() => downloadHandbook(handbook.project_id));
  const open = handbook.counts.required - handbook.counts.required_approved;
  const errors = findings.filter((f) => f.severity === 'error');
  return (
    <section className="space-y-3 rounded-lg border border-border bg-surface-elevated shadow-sm px-4 py-3" data-testid="handbook-head">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-content-primary">{handbook.title}</h2>
          {handbook.edition ? <p className="text-sm text-content-secondary">{handbook.edition}</p> : null}
        </div>
        <Button
          variant="primary"
          size="sm"
          icon={<Download size={14} />}
          loading={download.isPending}
          onClick={() => download.mutate()}
          data-testid="handbook-download"
        >
          {t('projectHandbook.download', { defaultValue: 'Download the handbook (PDF)' })}
        </Button>
      </div>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          [t('projectHandbook.counts.chapters', { defaultValue: 'Chapters' }), handbook.counts.chapters],
          [t('projectHandbook.counts.approved', { defaultValue: 'Approved' }), handbook.counts.approved],
          [t('projectHandbook.counts.in_review', { defaultValue: 'In review' }), handbook.counts.in_review],
          [
            t('projectHandbook.counts.required_open', { defaultValue: 'Required, still open' }),
            `${open} / ${handbook.counts.required}`,
          ],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <dt className="text-xs text-content-tertiary">{label}</dt>
            <dd className="text-lg font-semibold tabular-nums text-content-primary">{value}</dd>
          </div>
        ))}
      </dl>
      {open > 0 ? (
        <p className="flex items-center gap-2 text-sm text-semantic-warning" data-testid="handbook-gate-note">
          <AlertTriangle size={14} aria-hidden />
          {t('projectHandbook.gate_note', {
            defaultValue: '{{count}} required chapters have no approved version. The gate reads this as not met.',
            count: open,
          })}
        </p>
      ) : null}
      {errors.length > 0 ? (
        <ul className="space-y-1" data-testid="handbook-findings">
          {errors.slice(0, 5).map((f, i) => (
            <li key={`${f.code}:${f.ref}:${i}`} className="text-sm text-content-primary">
              {findingText(tf, f.code)}
              <span className="ml-1.5 font-mono text-xs text-content-tertiary">{f.ref}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function CreateHandbook({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const create = useHandbookAction(() => createHandbook(projectId, { title, edition: '' }), onDone);
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="min-w-[16rem] flex-1">
        <span className="mb-1 block text-xs font-medium text-content-secondary">
          {t('projectHandbook.title_field', { defaultValue: 'Title of the handbook' })}
        </span>
        <input
          className="w-full rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
          value={title}
          maxLength={255}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()} data-testid="handbook-create">
        {t('projectHandbook.create', { defaultValue: 'Create the handbook' })}
      </Button>
    </div>
  );
}

export function ProjectHandbookPage() {
  const { t } = useTranslation();
  const { projectId = '' } = useParams<{ projectId: string }>();
  const projectName = useProjectName(projectId);
  const [params, setParams] = useSearchParams();
  const invalidate = useInvalidateHandbook(projectId);

  const requested = params.get('tab') as Tab | null;
  const tab: Tab = requested && TABS.includes(requested) ? requested : 'chapters';

  const handbookQ = useHandbook(projectId);
  const handbook = handbookQ.data ?? null;
  const findingsQ = useFindings(projectId, !!handbook);

  const header = (
    <>
      <Breadcrumb
        items={[
          { label: t('projects.title', { defaultValue: 'Projects' }), to: '/projects' },
          { label: projectName ?? t('projectHandbook.project', { defaultValue: 'Project' }), to: `/projects/${projectId}` },
          { label: t('projectHandbook.title', { defaultValue: 'Project handbook' }) },
        ]}
      />
      <div>
        <h1 className="text-xl font-semibold text-content-primary">{t('projectHandbook.title', { defaultValue: 'Project handbook' })}</h1>
        <p className="text-sm text-content-secondary">
          {t('projectHandbook.subtitle', {
            defaultValue: 'How the project is run: principles, organisation, communication rules and the data room, with an owner and an approval for every chapter.',
          })}
        </p>
      </div>
    </>
  );

  if (handbookQ.isLoading) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-handbook-page">
        {header}
        <SkeletonTable rows={6} columns={4} />
      </div>
    );
  }
  if (handbookQ.isError) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-handbook-page">
        {header}
        <ErrorState
          title={t('projectHandbook.load_failed', { defaultValue: 'The project handbook could not be loaded' })}
          hint={refusalText(t as TFn, handbookQ.error)}
          onRetry={() => handbookQ.refetch()}
        />
      </div>
    );
  }
  if (!handbook) {
    return (
      <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-handbook-page">
        {header}
        <EmptyState
          icon={<BookOpen size={28} />}
          title={t('projectHandbook.empty_title', { defaultValue: 'No project handbook yet' })}
          description={t('projectHandbook.empty_body', {
            defaultValue: 'The handbook lays out the chapters of the pinned catalogue, each with an owner and a four-eyes approval. Records of other modules, such as stakeholders and positions, are read live and never copied.',
          })}
        />
        <CreateHandbook projectId={projectId} onDone={invalidate} />
      </div>
    );
  }

  const chapters = handbook.chapters;
  const active = chapters.find((c) => c.code === params.get('chapter')) ?? chapters[0];
  const canManage = chapters.some((c) => c.can?.approve.applies !== undefined) && !!chapters[0]?.can;
  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: false });
  };

  return (
    <div className="space-y-5 animate-fade-in bg-surface-page rounded-2xl p-4 sm:p-5" data-testid="project-handbook-page">
      {header}
      <Head handbook={handbook} findings={findingsQ.data ?? []} />
      <TabBar<Tab>
        ariaLabel={t('projectHandbook.tabs.label', { defaultValue: 'Project handbook sections' })}
        activeId={tab}
        onChange={(id) => setParam('tab', id === 'chapters' ? null : id)}
        idPrefix="project-handbook"
        tabs={[
          { id: 'chapters', label: t('projectHandbook.tabs.chapters', { defaultValue: 'Chapters' }), icon: <BookOpen size={14} /> },
          { id: 'data_room', label: t('projectHandbook.tabs.data_room', { defaultValue: 'Data room' }), icon: <FolderTree size={14} /> },
        ]}
      />
      {tab === 'data_room' ? (
        <DataRoomTab projectId={projectId} canManage={canManage} onChanged={invalidate} />
      ) : active ? (
        <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
          <ChapterList chapters={chapters} active={active.code} onPick={(code) => setParam('chapter', code)} />
          <ChapterPanel key={active.code} projectId={projectId} code={active.code} onChanged={invalidate} />
        </div>
      ) : null}
    </div>
  );
}
