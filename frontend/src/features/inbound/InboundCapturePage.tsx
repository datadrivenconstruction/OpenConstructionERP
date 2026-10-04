// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Inbound Capture (admin) - a triage view of what came in through the capture
// gateway. The capture endpoints (POST email / provider webhook) are driven by
// external systems; this page lets an admin search, filter and page through the
// messages that landed as incoming correspondence for the active project, open
// the correspondence record each one became, and see the configured document
// sources (watched folders) that feed the same record. It is read-only: managing
// a source lives on the Document Connectors page, linked from here.

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import {
  Mailbox,
  Inbox,
  HardDrive,
  Paperclip,
  FileText,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  ListTodo,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, ErrorState, SkeletonTable, DismissibleInfo } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { listConnectorSources } from '@/features/connectors/api';
import type { ConnectorSource } from '@/features/connectors/types';
import { CreateTaskFromSourceDialog } from '@/features/tasks';
import { listCapturedMessages } from './api';
import type { InboundAttachment, InboundMessage } from './types';
import {
  EMPTY_INBOUND_FILTERS,
  InboundFilters,
  filterInboundMessages,
  hasActiveInboundFilters,
  inboundChannels,
  type InboundFilterState,
} from './InboundFilters';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';

// How many messages we pull per page from the paginated read endpoint. The
// search / filter refinement runs over whichever page is loaded.
const PAGE_SIZE = 25;

// A short, readable timestamp for the captured time. The value is the provider's
// ISO sent_at; an unparseable / blank value falls back to a dash rather than
// rendering "Invalid Date".
function whenLabel(iso: string): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(getIntlLocale());
}

// Human-readable byte size for an attachment; blank when the size is unknown so
// the row shows just the filename rather than "0 B".
function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = value >= 10 || unit === 0 ? Math.round(value).toString() : fmtFixed(value, 1);
  return `${rounded} ${units[unit]}`;
}

// The attachment list surfaces each file's name (and size / type) instead of a
// bare count. We do NOT fetch binaries here: the capture payload carries only a
// storage hint, so names are informational and shown as a tooltip target. A
// real download would need a per-attachment endpoint (not yet exposed).
function AttachmentList({ attachments }: { attachments: InboundAttachment[] }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-1 border-t border-border-light pt-1.5">
      <span className="inline-flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
        <Paperclip className="h-3 w-3" aria-hidden />
        {t('inbound.attachments_label', { defaultValue: 'Attachments' })} ({attachments.length})
      </span>
      <ul className="flex flex-col gap-0.5">
        {attachments.map((a, i) => {
          const size = formatBytes(a.size_bytes);
          return (
            <li
              key={`${a.filename}-${i}`}
              className="flex items-center gap-1.5 text-xs text-content-secondary"
              title={a.storage_hint || a.content_type || undefined}
            >
              <FileText className="h-3 w-3 shrink-0 text-content-tertiary" aria-hidden />
              <span className="truncate">
                {a.filename || t('inbound.attachment_unnamed', { defaultValue: '(unnamed file)' })}
              </span>
              {size ? <span className="shrink-0 text-content-tertiary">{`· ${size}`}</span> : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// A captured message opens the correspondence record it became. There is no
// per-record correspondence route today, so we deep-link to the project's
// correspondence register (the closest verified target) and show the reference
// so the row is easy to find there.
function CapturedRow({
  msg,
  onCreateTask,
}: {
  msg: InboundMessage;
  /** Open the "Create task" quick-create prefilled from this captured message. */
  onCreateTask: (msg: InboundMessage) => void;
}) {
  const { t } = useTranslation();
  const to = `/projects/${encodeURIComponent(msg.project_id)}/correspondence`;
  return (
    <Link
      to={to}
      className="group block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
      aria-label={t('inbound.open_record_aria', {
        defaultValue: 'Open correspondence record {{ref}}',
        ref: msg.reference_number || msg.subject || msg.correspondence_id,
      })}
    >
      <Card
        padding="none"
        className="space-y-1.5 p-3 transition-colors group-hover:border-border group-hover:bg-surface-secondary/40"
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">
            {msg.reference_number || t('inbound.no_reference', { defaultValue: '(no reference)' })}
          </span>
          {msg.channel ? <Badge variant="blue">{msg.channel}</Badge> : null}
          {msg.deduplicated ? (
            <Badge variant="neutral">{t('inbound.deduplicated', { defaultValue: 'Duplicate' })}</Badge>
          ) : null}
          <span className="ms-auto text-xs text-content-tertiary">{whenLabel(msg.sent_at)}</span>
        </div>
        <p className="truncate text-sm text-content-secondary">
          {msg.subject || t('inbound.no_subject', { defaultValue: '(no subject)' })}
        </p>
        <p className="truncate text-xs text-content-tertiary">
          {t('inbound.from', { defaultValue: 'From' })}: {msg.sender || '-'}
        </p>
        {msg.attachments.length > 0 ? <AttachmentList attachments={msg.attachments} /> : null}
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue-text">
            {t('inbound.open_record', { defaultValue: 'Open correspondence' })}
            <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </span>
          <Button
            variant="secondary"
            size="sm"
            icon={<ListTodo size={13} />}
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onCreateTask(msg);
            }}
            data-testid={`inbound-create-task-${msg.correspondence_id}`}
            title={t('inbound.create_task_hint', { defaultValue: 'Turn this message into a task' })}
          >
            {t('inbound.create_task', { defaultValue: 'Create task' })}
          </Button>
        </div>
      </Card>
    </Link>
  );
}

function SourceRow({ source }: { source: ConnectorSource }) {
  const { t } = useTranslation();
  return (
    <Card className="space-y-1.5 p-3" padding="none">
      <div className="flex flex-wrap items-center gap-2">
        <HardDrive className="h-4 w-4 shrink-0 text-content-tertiary" />
        <span className="text-sm font-semibold text-content-primary">{source.name}</span>
        <Badge variant="neutral">{source.kind}</Badge>
        {!source.enabled ? (
          <Badge variant="warning">{t('inbound.source_disabled', { defaultValue: 'Disabled' })}</Badge>
        ) : null}
      </div>
      <code className="block truncate rounded bg-surface-secondary px-2 py-1 text-xs text-content-secondary">
        {source.root_path}
      </code>
    </Card>
  );
}

export function InboundCapturePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId ?? activeProjectId ?? '';

  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<InboundFilterState>(EMPTY_INBOUND_FILTERS);
  const [taskSourceMsg, setTaskSourceMsg] = useState<InboundMessage | null>(null);

  // A different project is a different mailbox: start from the first page and a
  // clean filter so a deep offset from the previous project cannot strand us on
  // an empty page.
  useEffect(() => {
    setOffset(0);
    setFilters(EMPTY_INBOUND_FILTERS);
  }, [projectId]);

  const capturedQ = useQuery({
    queryKey: ['inbound', 'captured', projectId, offset],
    queryFn: () => listCapturedMessages(projectId, { offset, limit: PAGE_SIZE }),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });

  const sourcesQ = useQuery({
    queryKey: ['connectors', 'sources', projectId],
    queryFn: () => listConnectorSources(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const pageItems = capturedQ.data?.items ?? [];
  const total = capturedQ.data?.total ?? 0;
  const sources = sourcesQ.data ?? [];

  const channels = useMemo(() => inboundChannels(pageItems), [pageItems]);
  const visible = useMemo(() => filterInboundMessages(pageItems, filters), [pageItems, filters]);
  const filtersActive = hasActiveInboundFilters(filters);

  // While paging, keepPreviousData holds the old page on screen; dim it so the
  // transition reads as a load rather than a stale result.
  const isPaging = capturedQ.isFetching && capturedQ.isPlaceholderData;
  const rangeStart = total === 0 ? 0 : offset + 1;
  const rangeEnd = offset + pageItems.length;
  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  const pageRangeLabel = t('inbound.page_range', {
    defaultValue: 'Showing {{start}}-{{end}} of {{total}}',
    start: rangeStart,
    end: rangeEnd,
    total,
  });

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="flex flex-wrap items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <Mailbox className="h-5 w-5" />
        </span>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-content-primary">
            {t('inbound.title', { defaultValue: 'Inbound Capture' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('inbound.subtitle', {
              defaultValue: 'Messages captured from email and chat, and the sources that feed the record.',
            })}
          </p>
        </div>
        <a
          href="/connectors"
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary"
        >
          {t('inbound.manage_sources', { defaultValue: 'Manage sources' })}
          <ArrowRight className="h-4 w-4" />
        </a>
      </header>

      <DismissibleInfo
        storageKey="inbound-capture-admin"
        title={t('inbound.intro_title', { defaultValue: 'What lands here' })}
      >
        {t('inbound.intro_body', {
          defaultValue:
            'An external mail or chat integration posts inbound messages to the capture gateway, which stores each as incoming correspondence on the project - deduplicated on the provider message id. Search, filter and page through what was captured here, open the correspondence record any message became, and see the watched-folder sources that import documents onto the same record.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('inbound.no_project', { defaultValue: 'No project selected' })}
          description={t('inbound.no_project_desc', {
            defaultValue: 'Select a project to see the messages captured against it.',
          })}
        />
      ) : (
        <>
          <section className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-content-secondary">
                {t('inbound.captured_heading', { defaultValue: 'Captured messages' })}
              </h2>
              {capturedQ.data ? <Badge variant="neutral">{total}</Badge> : null}
            </div>

            {capturedQ.isLoading ? (
              <SkeletonTable rows={4} />
            ) : capturedQ.isError ? (
              <ErrorState
                title={getErrorMessage(capturedQ.error)}
                onRetry={() => {
                  void capturedQ.refetch();
                }}
              />
            ) : total === 0 ? (
              <EmptyState
                icon={<Mailbox className="h-6 w-6" />}
                title={t('inbound.none_captured', { defaultValue: 'Nothing captured yet' })}
                description={t('inbound.none_captured_desc', {
                  defaultValue:
                    'Inbound emails and chat messages delivered to the capture gateway will appear here.',
                })}
              />
            ) : (
              <>
                <InboundFilters value={filters} onChange={setFilters} channels={channels} />

                <p className="text-xs text-content-tertiary" aria-live="polite">
                  {filtersActive
                    ? t('inbound.filter_result_count', {
                        defaultValue: '{{shown}} of {{onPage}} on this page match',
                        shown: visible.length,
                        onPage: pageItems.length,
                      })
                    : pageRangeLabel}
                </p>

                {visible.length === 0 ? (
                  <EmptyState
                    icon={<Inbox className="h-6 w-6" />}
                    title={t('inbound.no_matches', { defaultValue: 'No messages match these filters' })}
                    description={t('inbound.no_matches_desc', {
                      defaultValue: 'Adjust the search or filters, or move to another page.',
                    })}
                    action={
                      filtersActive
                        ? {
                            label: t('inbound.filter_clear_all', { defaultValue: 'Clear filters' }),
                            onClick: () => setFilters(EMPTY_INBOUND_FILTERS),
                          }
                        : undefined
                    }
                  />
                ) : (
                  <div
                    className={`grid gap-2 ${isPaging ? 'opacity-60 transition-opacity' : ''}`}
                    aria-busy={isPaging}
                  >
                    {visible.map((m) => (
                      <CapturedRow key={m.correspondence_id} msg={m} onCreateTask={setTaskSourceMsg} />
                    ))}
                  </div>
                )}

                {canPrev || canNext ? (
                  <div className="flex items-center justify-between gap-3 pt-1">
                    <span className="text-xs text-content-tertiary">{pageRangeLabel}</span>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<ChevronLeft className="h-4 w-4" aria-hidden />}
                        disabled={!canPrev || capturedQ.isFetching}
                        onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                      >
                        {t('inbound.prev', { defaultValue: 'Previous' })}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<ChevronRight className="h-4 w-4" aria-hidden />}
                        iconPosition="right"
                        disabled={!canNext || capturedQ.isFetching}
                        onClick={() => setOffset((o) => o + PAGE_SIZE)}
                      >
                        {t('inbound.next', { defaultValue: 'Next' })}
                      </Button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </section>

          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-content-secondary">
                {t('inbound.sources_heading', { defaultValue: 'Configured sources' })}
              </h2>
              {sourcesQ.data ? <Badge variant="neutral">{sources.length}</Badge> : null}
            </div>
            {sourcesQ.isLoading ? (
              <SkeletonTable rows={2} />
            ) : sourcesQ.isError ? (
              <p className="text-sm text-semantic-error">{getErrorMessage(sourcesQ.error)}</p>
            ) : sources.length === 0 ? (
              <EmptyState
                icon={<HardDrive className="h-6 w-6" />}
                title={t('inbound.no_sources', { defaultValue: 'No sources configured' })}
                description={t('inbound.no_sources_desc', {
                  defaultValue: 'Add a watched folder on the Document Connectors page to feed the record.',
                })}
              />
            ) : (
              <div className="grid gap-2">
                {sources.map((s) => (
                  <SourceRow key={s.id} source={s} />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* Create task quick action — prefilled from this captured message. It
          became a correspondence row (see the module doc comment above), so
          the task links back the same way a task raised from a hand-entered
          correspondence entry would. */}
      {taskSourceMsg && (
        <CreateTaskFromSourceDialog
          projectId={taskSourceMsg.project_id || projectId}
          sourceType="inbound_capture"
          sourceId={taskSourceMsg.correspondence_id}
          sourceLabel={taskSourceMsg.reference_number || taskSourceMsg.correspondence_id}
          defaultTitle={
            taskSourceMsg.subject || t('inbound.no_subject', { defaultValue: '(no subject)' })
          }
          defaultDescription={t('inbound.task_desc_default', {
            defaultValue: 'Follow up on captured message {{ref}} from {{sender}}.',
            ref: taskSourceMsg.reference_number || taskSourceMsg.correspondence_id,
            sender: taskSourceMsg.sender || t('inbound.unknown_sender', { defaultValue: 'unknown sender' }),
          })}
          onClose={() => setTaskSourceMsg(null)}
        />
      )}
    </div>
  );
}
