// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Event Reconciliation - stitch the scattered trail of one event back together.
// A single site event surfaces as separate records across modules (a change
// order, a variation, a piece of correspondence, an MoC entry); the engine scores
// every candidate pair and proposes explainable links between the records that
// are really about the same event. This page assembles the thread around a seed
// event, shows each suggested correlation with the signals that fired and a
// confidence band, and lets a reviewer confirm or reject the link on the evidence.
// Confirm / reject persist through the project-scoped decision endpoint; the
// thread and the decision ledger refresh so the timeline reflects the call.

import { Fragment, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Link2,
  Check,
  X,
  Search,
  Clock,
  Tag,
  User,
  Inbox,
  CircleCheck,
  CircleX,
  Sparkles,
  Network,
  ArrowRight,
} from 'lucide-react';
import {
  Card,
  Badge,
  CollapsibleSection,
  EmptyState,
  SkeletonTable,
  DismissibleInfo,
  ConfidenceBadge,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getEventThread, listRecordLinks, decideRecordLink } from './api';
import type { LinkDecision, LinkStatus, ThreadLink, ThreadRecord } from './types';
import { fmtList, getIntlLocale } from '@/shared/lib/formatters';

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_VARIANT: Record<LinkStatus, BadgeVariant> = {
  suggested: 'blue',
  confirmed: 'success',
  rejected: 'error',
};

// Human label for a persisted review state. New keys (reported for central
// en.ts addition) fall back to English via defaultValue.
function statusLabel(t: (k: string, o: { defaultValue: string }) => string, s: LinkStatus): string {
  return t(`reconciliation.status_${s}`, {
    defaultValue: { suggested: 'Suggested', confirmed: 'Confirmed', rejected: 'Rejected' }[s],
  });
}

// Human label for a record type token the engine projects every source onto.
function recordTypeLabel(
  t: (k: string, o: { defaultValue: string }) => string,
  type: string,
): string {
  const known: Record<string, string> = {
    correspondence: 'Correspondence',
    change_order: 'Change order',
    variation_request: 'Variation request',
    variation_order: 'Variation order',
    notice: 'Notice',
    moc: 'Management of change',
  };
  return t(`reconciliation.type_${type}`, { defaultValue: known[type] ?? type });
}

// Human label for an explainable signal the engine reports on a link.
function reasonLabel(t: (k: string, o: { defaultValue: string }) => string, reason: string): string {
  const known: Record<string, string> = {
    shared_reference: 'Shared reference code',
    subject_match: 'Same subject',
    party_and_date_proximity: 'Same party, close in time',
    embedding_similarity: 'Similar wording',
  };
  return t(`reconciliation.reason_${reason}`, { defaultValue: known[reason] ?? reason });
}

// A short, readable timestamp. The wire value is an ISO string of varying width;
// an unparseable / blank value falls back to a dash rather than "Invalid Date".
function whenLabel(iso: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(getIntlLocale());
}

// The canonical key the seed field submits for a record. Mirrors the engine's
// "<record_type>:<record_id>" seed form so clicking a record loads its thread.
function recordKey(rec: ThreadRecord): string {
  return `${rec.record_type}:${rec.record_id}`;
}

function RecordRow({
  rec,
  onSeed,
}: {
  rec: ThreadRecord;
  onSeed: (key: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Card className="space-y-1.5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="neutral">{recordTypeLabel(t, rec.record_type)}</Badge>
        {rec.is_seed && (
          <Badge variant="blue">{t('reconciliation.seed', { defaultValue: 'Seed' })}</Badge>
        )}
        <span className="ms-auto inline-flex items-center gap-1 text-xs text-content-tertiary">
          <Clock className="h-3.5 w-3.5" />
          {whenLabel(rec.occurred_at)}
        </span>
      </div>
      <p className="text-sm font-medium text-content-primary">
        {rec.subject || t('reconciliation.no_subject', { defaultValue: '(no subject)' })}
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-content-tertiary">
        {rec.party && (
          <span className="inline-flex items-center gap-1">
            <User className="h-3.5 w-3.5" />
            {rec.party}
          </span>
        )}
        {rec.refs.length > 0 && (
          <span className="inline-flex items-center gap-1">
            <Tag className="h-3.5 w-3.5" />
            {fmtList(rec.refs)}
          </span>
        )}
        {!rec.is_seed && (
          <button
            type="button"
            onClick={() => onSeed(recordKey(rec))}
            className="ms-auto inline-flex items-center gap-1 rounded text-oe-blue hover:underline"
          >
            <Search className="h-3.5 w-3.5" />
            {t('reconciliation.use_as_seed', { defaultValue: 'Thread from here' })}
          </button>
        )}
      </div>
    </Card>
  );
}

function LinkRow({
  link,
  recordLabelFor,
  onDecide,
  pendingDecision,
}: {
  link: ThreadLink;
  recordLabelFor: (type: string, id: string) => string;
  onDecide: (link: ThreadLink, decision: LinkDecision) => void;
  pendingDecision: LinkDecision | null;
}) {
  const { t } = useTranslation();
  const busy = pendingDecision !== null;
  return (
    <Card className="space-y-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <ConfidenceBadge score={link.confidence} showScore />
        <Badge variant={STATUS_VARIANT[link.status]}>{statusLabel(t, link.status)}</Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm text-content-primary">
        <span className="rounded bg-surface-secondary px-2 py-0.5">
          {recordLabelFor(link.left_type, link.left_id)}
        </span>
        <Link2 className="h-4 w-4 shrink-0 text-content-tertiary" />
        <span className="rounded bg-surface-secondary px-2 py-0.5">
          {recordLabelFor(link.right_type, link.right_id)}
        </span>
      </div>

      {link.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {link.reasons.map((reason) => (
            <span
              key={reason}
              className="inline-flex items-center gap-1 rounded-full border border-border-light px-2 py-0.5 text-2xs text-content-secondary"
            >
              <Sparkles className="h-3 w-3 text-oe-blue" />
              {reasonLabel(t, reason)}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 pt-0.5">
        <button
          type="button"
          disabled={busy || link.status === 'confirmed'}
          onClick={() => onDecide(link, 'confirmed')}
          className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Check className="h-4 w-4" />
          {pendingDecision === 'confirmed'
            ? t('reconciliation.confirming', { defaultValue: 'Confirming...' })
            : t('reconciliation.confirm', { defaultValue: 'Confirm link' })}
        </button>
        <button
          type="button"
          disabled={busy || link.status === 'rejected'}
          onClick={() => onDecide(link, 'rejected')}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-light bg-surface-primary px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <X className="h-4 w-4" />
          {pendingDecision === 'rejected'
            ? t('reconciliation.rejecting', { defaultValue: 'Rejecting...' })
            : t('reconciliation.reject', { defaultValue: 'Reject' })}
        </button>
      </div>
    </Card>
  );
}

/* ── How it works + connects ─────────────────────────────────────────────
 * Compact at-a-glance flow so a reviewer sees what Event Reconciliation does
 * and which sibling modules the records it stitches together come from.
 * Mirrors the approved norm-expansion pattern. */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

function HowReconciliationWork() {
  const { t } = useTranslation();
  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Search size={14} className="text-oe-blue" />,
      title: t('reconciliation.flow_1_title', { defaultValue: 'Pick a seed event' }),
      desc: t('reconciliation.flow_1_desc', {
        defaultValue: 'Start from one record: a change order, variation or letter.',
      }),
    },
    {
      icon: <Sparkles size={14} className="text-oe-blue" />,
      title: t('reconciliation.flow_2_title', { defaultValue: 'See suggested links' }),
      desc: t('reconciliation.flow_2_desc', {
        defaultValue: 'The engine scores every candidate pair and names the signals that fired.',
      }),
    },
    {
      icon: <Link2 size={14} className="text-oe-blue" />,
      title: t('reconciliation.flow_3_title', { defaultValue: 'Weigh the evidence' }),
      desc: t('reconciliation.flow_3_desc', {
        defaultValue: 'Each correlation shows its reasons and a confidence band.',
      }),
    },
    {
      icon: <Check size={14} className="text-oe-blue" />,
      title: t('reconciliation.flow_4_title', { defaultValue: 'Confirm or reject' }),
      desc: t('reconciliation.flow_4_desc', {
        defaultValue: 'Your decision shapes the thread and is recorded for the project.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="reconciliation.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('reconciliation.flow_title', {
        defaultValue: 'How reconciliation works, and what it connects to',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('reconciliation.flow_intro', {
          defaultValue:
            'One site event scatters into separate records across modules; assemble them into a single thread and confirm the links. Enter a seed record above to start.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-primary p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-oe-blue-subtle">
                  {s.icon}
                </span>
                <span className="text-xs font-semibold text-content-primary">{s.title}</span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('reconciliation.flow_connects', { defaultValue: 'Reconciles records from:' })}
        </span>{' '}
        <ModLink to="/variations">
          {t('reconciliation.mod_variations', { defaultValue: 'Variations' })}
        </ModLink>
        {' · '}
        <ModLink to="/changeorders">
          {t('reconciliation.mod_change_orders', { defaultValue: 'Change orders' })}
        </ModLink>
        {' · '}
        <ModLink to="/correspondence">
          {t('reconciliation.mod_correspondence', { defaultValue: 'Correspondence' })}
        </ModLink>
        {' · '}
        <ModLink to="/moc">
          {t('reconciliation.mod_moc', { defaultValue: 'Management of Change' })}
        </ModLink>
        {' · '}
        <ModLink to="/reports">
          {t('reconciliation.mod_reports', { defaultValue: 'Reports' })}
        </ModLink>
      </div>
    </CollapsibleSection>
  );
}

export function ReconciliationPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { projectId: routeProjectId } = useParams();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId ?? activeProjectId ?? '';

  // The seed event currently being threaded (a "<record_type>:<record_id>" key
  // or a subject line). `eventInput` is the editable field; `eventKey` is the
  // submitted value the thread query runs on, so typing doesn't refetch on
  // every keystroke.
  const [eventInput, setEventInput] = useState('');
  const [eventKey, setEventKey] = useState('');
  // The link a decision is in flight for, keyed canonically, plus which way.
  const [pending, setPending] = useState<{ key: string; decision: LinkDecision } | null>(null);

  const threadQuery = useQuery({
    queryKey: ['reconciliation', 'thread', projectId, eventKey],
    queryFn: () => getEventThread(projectId, eventKey),
    enabled: !!projectId && eventKey.trim() !== '',
    retry: false,
    staleTime: 30_000,
  });

  const decisionsQuery = useQuery({
    queryKey: ['reconciliation', 'record-links', projectId],
    queryFn: () => listRecordLinks(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const decideMutation = useMutation({
    mutationFn: ({ link, decision }: { link: ThreadLink; decision: LinkDecision }) =>
      decideRecordLink(projectId, {
        left_type: link.left_type,
        left_id: link.left_id,
        right_type: link.right_type,
        right_id: link.right_id,
        relation: link.relation,
        status: decision,
        confidence: link.confidence,
      }),
    onSuccess: (_row, { decision }) => {
      addToast({
        type: 'success',
        title:
          decision === 'confirmed'
            ? t('reconciliation.confirmed_toast', { defaultValue: 'Link confirmed' })
            : t('reconciliation.rejected_toast', { defaultValue: 'Link rejected' }),
      });
      void queryClient.invalidateQueries({
        queryKey: ['reconciliation', 'thread', projectId, eventKey],
      });
      void queryClient.invalidateQueries({
        queryKey: ['reconciliation', 'record-links', projectId],
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('reconciliation.decision_failed', { defaultValue: 'Could not save the decision' }),
        message: getErrorMessage(err),
      });
    },
    onSettled: () => setPending(null),
  });

  const linkKeyOf = (link: ThreadLink): string =>
    `${link.left_type}:${link.left_id}|${link.right_type}:${link.right_id}`;

  const handleDecide = (link: ThreadLink, decision: LinkDecision) => {
    setPending({ key: linkKeyOf(link), decision });
    decideMutation.mutate({ link, decision });
  };

  const runSearch = () => setEventKey(eventInput.trim());

  // Map an endpoint to a readable label. The thread in view is consulted first,
  // then the subject the API resolved for the endpoint; the id form is the last
  // resort for a record that has been deleted. The recorded-decisions log needs
  // the second of those: it outlives the thread each decision was taken in, so
  // every row there used to fall straight through to "<type> <short-id>".
  const thread = threadQuery.data;
  const recordLabelFor = (type: string, id: string, subject?: string | null): string => {
    const rec = thread?.records.find((r) => r.record_type === type && r.record_id === id);
    const name = rec?.subject || subject?.trim();
    if (name) return `${recordTypeLabel(t, type)}: ${name}`;
    const shortId = id.length > 8 ? `${id.slice(0, 8)}...` : id;
    return `${recordTypeLabel(t, type)} ${shortId}`;
  };

  if (!projectId) {
    return (
      <div className="p-4">
        <EmptyState
          icon={<Link2 className="h-6 w-6" />}
          title={t('reconciliation.no_project_title', { defaultValue: 'No project selected' })}
          description={t('reconciliation.no_project_desc', {
            defaultValue: 'Select a project to reconcile its cross-channel event records.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-1">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold text-content-primary">
          <Link2 className="h-5 w-5" />
          {t('reconciliation.title', { defaultValue: 'Event Reconciliation' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('reconciliation.subtitle', {
            defaultValue:
              'Stitch the scattered records of one event back together and confirm the links.',
          })}
        </p>
      </div>

      <HowReconciliationWork />

      <DismissibleInfo
        storageKey="reconciliation-intro"
        title={t('reconciliation.intro_title', { defaultValue: 'How reconciliation works' })}
      >
        {t('reconciliation.intro_body', {
          defaultValue:
            'One site event scatters across modules - a change order, a variation, a piece of correspondence, a management-of-change entry - each in its own record. The engine scores every candidate pair and suggests links between the records that are really about the same event, naming the signals that fired (a shared reference code, the same subject, the same party close in time, similar wording) and a confidence band. Enter a seed (a record key like change_order:<id>, or a subject line) to assemble its thread, then confirm or reject each suggested link. Your decisions are saved and shape the thread - a rejected link no longer stitches its records together.',
        })}
      </DismissibleInfo>

      <Card className="space-y-3 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Search className="h-4 w-4" />
          {t('reconciliation.seed_title', { defaultValue: 'Assemble a thread' })}
        </h2>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="flex flex-1 flex-col gap-1 text-sm text-content-secondary">
            {t('reconciliation.seed_label', { defaultValue: 'Seed event' })}
            <input
              value={eventInput}
              onChange={(e) => setEventInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') runSearch();
              }}
              placeholder={t('reconciliation.seed_ph', {
                defaultValue: 'change_order:<id> or a subject line',
              })}
              className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-sm text-content-primary"
            />
          </label>
          <button
            type="button"
            disabled={eventInput.trim() === ''}
            onClick={runSearch}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Search className="h-4 w-4" />
            {t('reconciliation.assemble', { defaultValue: 'Assemble thread' })}
          </button>
        </div>
        <p className="text-xs text-content-tertiary">
          {t('reconciliation.seed_hint', {
            defaultValue:
              'A seed is one record (type:id) or a subject. The thread grows to every record linked to it above the engine threshold.',
          })}
        </p>
      </Card>

      {eventKey.trim() !== '' && (
        <div className="space-y-3">
          {threadQuery.isLoading ? (
            <SkeletonTable rows={3} />
          ) : threadQuery.isError ? (
            <EmptyState
              icon={<Inbox className="h-6 w-6" />}
              title={t('reconciliation.thread_error_title', {
                defaultValue: 'Could not assemble the thread',
              })}
              description={getErrorMessage(threadQuery.error)}
            />
          ) : !thread || thread.records.length === 0 ? (
            <EmptyState
              icon={<Search className="h-6 w-6" />}
              title={t('reconciliation.no_match_title', { defaultValue: 'No records matched' })}
              description={t('reconciliation.no_match_desc', {
                defaultValue:
                  'No record matched that seed in this project. Check the record key, or try a subject line.',
              })}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-xs text-content-tertiary">
                <span className="inline-flex items-center gap-1">
                  <CircleCheck className="h-3.5 w-3.5 text-semantic-success" />
                  {t('reconciliation.confirmed_count', {
                    defaultValue: '{{count}} confirmed',
                    count: thread.confirmed_count,
                  })}
                </span>
                <span className="inline-flex items-center gap-1">
                  <CircleX className="h-3.5 w-3.5 text-semantic-error" />
                  {t('reconciliation.rejected_count', {
                    defaultValue: '{{count}} rejected',
                    count: thread.rejected_count,
                  })}
                </span>
              </div>

              <section className="space-y-2">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                  <Link2 className="h-4 w-4" />
                  {t('reconciliation.suggested_links', { defaultValue: 'Suggested correlations' })}
                  <Badge variant="neutral">{thread.links.length}</Badge>
                </h2>
                {thread.links.length === 0 ? (
                  <EmptyState
                    icon={<Link2 className="h-6 w-6" />}
                    title={t('reconciliation.no_links_title', { defaultValue: 'No correlations' })}
                    description={t('reconciliation.no_links_desc', {
                      defaultValue:
                        'The engine found no other record linked to this seed above its threshold.',
                    })}
                  />
                ) : (
                  <div className="space-y-2">
                    {thread.links.map((link) => {
                      const key = linkKeyOf(link);
                      const decision =
                        pending && pending.key === key && decideMutation.isPending
                          ? pending.decision
                          : null;
                      return (
                        <LinkRow
                          key={key}
                          link={link}
                          recordLabelFor={recordLabelFor}
                          onDecide={handleDecide}
                          pendingDecision={decision}
                        />
                      );
                    })}
                  </div>
                )}
              </section>

              <section className="space-y-2">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                  <Clock className="h-4 w-4" />
                  {t('reconciliation.timeline', { defaultValue: 'Event timeline' })}
                  <Badge variant="neutral">{thread.records.length}</Badge>
                </h2>
                <div className="space-y-2">
                  {thread.records.map((rec) => (
                    <RecordRow
                      key={recordKey(rec)}
                      rec={rec}
                      onSeed={(key) => {
                        setEventInput(key);
                        setEventKey(key);
                      }}
                    />
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      )}

      <section className="space-y-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <CircleCheck className="h-4 w-4" />
          {t('reconciliation.decisions', { defaultValue: 'Recorded decisions' })}
        </h2>
        {decisionsQuery.isLoading ? (
          <SkeletonTable rows={2} />
        ) : decisionsQuery.isError ? (
          <p className="text-sm text-semantic-error">{getErrorMessage(decisionsQuery.error)}</p>
        ) : !decisionsQuery.data || decisionsQuery.data.length === 0 ? (
          <EmptyState
            icon={<CircleCheck className="h-6 w-6" />}
            title={t('reconciliation.no_decisions_title', { defaultValue: 'No decisions yet' })}
            description={t('reconciliation.no_decisions_desc', {
              defaultValue:
                'Confirm or reject a suggested correlation above and it will be recorded here.',
            })}
          />
        ) : (
          <div className="space-y-2">
            {decisionsQuery.data.map((row) => (
              <Card key={row.id} className="flex flex-wrap items-center gap-2 p-3 text-sm">
                <Badge variant={STATUS_VARIANT[row.status] ?? 'neutral'}>
                  {statusLabel(t, row.status)}
                </Badge>
                <span className="rounded bg-surface-secondary px-2 py-0.5 text-content-primary">
                  {recordLabelFor(row.left_type, row.left_id, row.left_subject)}
                </span>
                <Link2 className="h-4 w-4 shrink-0 text-content-tertiary" />
                <span className="rounded bg-surface-secondary px-2 py-0.5 text-content-primary">
                  {recordLabelFor(row.right_type, row.right_id, row.right_subject)}
                </span>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default ReconciliationPage;
