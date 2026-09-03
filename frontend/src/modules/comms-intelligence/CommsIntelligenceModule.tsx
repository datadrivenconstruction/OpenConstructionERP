// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Comms Intelligence — the smart layer over project correspondence.
 *
 * Three views on one screen:
 *  - Review queue: every suggested analysis with its confidence, extracted
 *    facts and the apply-on-confirm suggestions. Confirm / dismiss is the
 *    human gate — nothing mutates the register until a person acts here.
 *  - Deadlines: who owes whom a response — overdue, due soon, awaiting.
 *  - Drafts: AI/template reply and chase-up text, copy-out only (the
 *    module never sends mail).
 */

import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepsNativeMenu, useMenu } from './ContextMenu';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Bot,
  Download,
  Mail,
  CheckCheck,
  ClipboardCopy,
  ClipboardList,
  Clock,
  Inbox,
  Loader2,
  MailQuestion,
  RefreshCw,
  Scale,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import {
  Badge,
  Button,
  ConfidenceBadge,
  DismissibleInfo,
  EmptyState,
  KpiBand,
  TabBar,
} from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet } from '@/shared/lib/api';
import { ComparePanel } from './ComparePanel';
import { TrackingTab } from './TrackingTab';
import { type Kind, deadlineSweep, fetchItem } from './registers-api';
import { RegisterEmailDialog } from './RegisterEmailDialog';
import { RegisterWorkspace } from './RegisterWorkspace';
import type { RegisterItemRow } from './registers-api';
import {
  type Analysis,
  type Dashboard,
  type DashboardEntry,
  type Draft,
  type EmailPreview,
  confirmAnalysis,
  createDraft,
  dismissAnalysis,
  emlDownloadUrl,
  fetchAnalyses,
  fetchBridgeStatus,
  fetchDashboard,
  openOutlookDraft,
  previewEmail,
  runAnalysis,
  setDraftStatus,
} from './api';

// ---------------------------------------------------------------------------
// Category presentation
// ---------------------------------------------------------------------------

const CATEGORY_VARIANT: Record<string, 'neutral' | 'blue' | 'purple' | 'success' | 'warning' | 'error'> = {
  quote: 'blue',
  rfi_response: 'purple',
  variation_notice: 'warning',
  delay_notice: 'error',
  claim: 'error',
  instruction: 'warning',
  approval: 'success',
  delivery: 'blue',
  general: 'neutral',
};

function CategoryBadge({ category }: { category: string | null }) {
  const { t } = useTranslation();
  if (!category) return null;
  return (
    <Badge variant={CATEGORY_VARIANT[category] ?? 'neutral'}>
      {t(`comms_intelligence.category.${category}`, { defaultValue: category.replace(/_/g, ' ') })}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Review queue row
// ---------------------------------------------------------------------------

function SuggestionLine({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-surface-secondary px-2 py-0.5 text-xs">
      <span className="text-text-tertiary">{label}</span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

function AnalysisRow({ analysis, projectId }: { analysis: Analysis; projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [emailOpen, setEmailOpen] = useState(false);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['comms-intelligence', projectId] });
  };

  const confirmMut = useMutation({
    mutationFn: () =>
      confirmAnalysis(analysis.id, {
        apply_status: true,
        apply_response_required_by: true,
        apply_link_rfi: true,
        apply_type: false,
      }),
    onSuccess: () => {
      addToast({ type: 'success', title: t('comms_intelligence.toast.confirmed', { defaultValue: 'Suggestion confirmed and applied' }) });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const dismissMut = useMutation({
    mutationFn: () => dismissAnalysis(analysis.id),
    onSuccess: () => {
      addToast({ type: 'info', title: t('comms_intelligence.toast.dismissed', { defaultValue: 'Suggestion dismissed' }) });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const aiMut = useMutation({
    mutationFn: () => runAnalysis(analysis.correspondence_id, true),
    onSuccess: () => {
      addToast({ type: 'success', title: t('comms_intelligence.toast.ai_done', { defaultValue: 'AI analysis complete' }) });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const draftMut = useMutation({
    mutationFn: (kind: 'reply' | 'chaser') => createDraft(analysis.correspondence_id, kind, '', true),
    onSuccess: (d) => setDraft(d),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const s = analysis.suggestions;
  const facts = analysis.extracted;
  const busy = confirmMut.isPending || dismissMut.isPending || aiMut.isPending;

  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="font-mono text-sm font-semibold hover:underline"
          onClick={() => setExpanded((v) => !v)}
          title={t('comms_intelligence.expand', { defaultValue: 'Show details' })}
        >
          {analysis.reference_number || analysis.correspondence_id.slice(0, 8)}
        </button>
        <CategoryBadge category={analysis.category} />
        <ConfidenceBadge score={analysis.confidence} showScore size="sm" />
        {analysis.source === 'ai' ? (
          <Badge variant="purple">
            <Bot className="mr-1 inline h-3 w-3" />
            {t('comms_intelligence.source_ai', { defaultValue: 'AI' })}
          </Badge>
        ) : (
          <Badge variant="neutral">{t('comms_intelligence.source_heuristic', { defaultValue: 'keywords' })}</Badge>
        )}
        {analysis.reply_needed && (
          <Badge variant="warning">
            <MailQuestion className="mr-1 inline h-3 w-3" />
            {t('comms_intelligence.reply_needed', { defaultValue: 'reply needed' })}
          </Badge>
        )}
        <span className="ml-auto flex items-center gap-1">
          {analysis.source !== 'ai' && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => aiMut.mutate()}
              disabled={busy}
              title={t('comms_intelligence.run_ai_hint', {
                defaultValue: 'Deepen with the configured AI provider (uses your AI budget)',
              })}
            >
              {aiMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {t('comms_intelligence.run_ai', { defaultValue: 'AI analyse' })}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => draftMut.mutate('reply')} disabled={draftMut.isPending}>
            {draftMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {t('comms_intelligence.draft_reply', { defaultValue: 'Draft reply' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEmailOpen(true)}>
            <Mail className="h-4 w-4" />
            {t('comms_intelligence.email', { defaultValue: 'Email' })}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => confirmMut.mutate()} disabled={busy}>
            <CheckCheck className="h-4 w-4" />
            {t('comms_intelligence.confirm', { defaultValue: 'Confirm' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => dismissMut.mutate()} disabled={busy}>
            <X className="h-4 w-4" />
            {t('comms_intelligence.dismiss', { defaultValue: 'Dismiss' })}
          </Button>
        </span>
      </div>

      {analysis.summary && <p className="mt-2 text-sm text-text-secondary">{analysis.summary}</p>}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {facts.prices.map((p) => (
          <SuggestionLine
            key={p.amount}
            label={t('comms_intelligence.price', { defaultValue: 'price' })}
            value={`${p.currency} ${p.amount}`}
          />
        ))}
        {facts.quote_number && (
          <SuggestionLine label={t('comms_intelligence.quote_no', { defaultValue: 'quote no.' })} value={facts.quote_number} />
        )}
        {facts.reference_numbers.map((r) => (
          <SuggestionLine key={r} label={t('comms_intelligence.ref', { defaultValue: 'ref' })} value={r} />
        ))}
        {s.response_required_by && (
          <SuggestionLine
            label={t('comms_intelligence.respond_by', { defaultValue: 'respond by' })}
            value={s.response_required_by}
          />
        )}
        {s.set_status && (
          <SuggestionLine label={t('comms_intelligence.set_status', { defaultValue: 'set status' })} value={s.set_status} />
        )}
        {s.link_rfi_id && (
          <SuggestionLine label={t('comms_intelligence.link_rfi', { defaultValue: 'link RFI' })} value={s.link_rfi_id.slice(0, 8)} />
        )}
      </div>

      {expanded && (
        <div className="mt-2 rounded bg-surface-secondary/50 p-2 text-xs text-text-secondary">
          {facts.commitments.length > 0 && (
            <ul className="list-inside list-disc">
              {facts.commitments.map((c, i) => (
                <li key={i}>
                  <span className="font-medium">{c.who}</span>: {c.what}
                  {c.when ? ` (${c.when})` : ''}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1 font-mono">
            {analysis.model_name || t('comms_intelligence.no_model', { defaultValue: 'no model - keyword pass' })} ·{' '}
            {analysis.prompt_version}
          </p>
        </div>
      )}

      {draft && <DraftCard draft={draft} onClose={() => setDraft(null)} />}
      {emailOpen && (
        <EmailPreviewDialog correspondenceId={analysis.correspondence_id} onClose={() => setEmailOpen(false)} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Email preview dialog - one payload behind preview / Outlook / .eml
// ---------------------------------------------------------------------------

function EmailPreviewDialog({ correspondenceId, onClose }: { correspondenceId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [extraTo, setExtraTo] = useState('');

  const bridgeQuery = useQuery({ queryKey: ['outlook-bridge-status'], queryFn: fetchBridgeStatus });
  const extras = extraTo
    .split(/[;,]/)
    .map((a) => a.trim())
    .filter(Boolean);
  const previewQuery = useQuery<EmailPreview>({
    queryKey: ['outlook-preview', correspondenceId, extras.join(';')],
    queryFn: () => previewEmail(correspondenceId, extras),
  });

  const outlookMut = useMutation({
    mutationFn: () => openOutlookDraft(correspondenceId, extras),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('comms_intelligence.toast.outlook_opened', {
          defaultValue: 'Draft opened in Outlook - review and press Send there',
        }),
      }),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const p = previewQuery.data;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg border border-border-light bg-surface-primary shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border-light p-3">
          <Mail className="h-4 w-4 text-text-tertiary" />
          <span className="text-sm font-semibold">
            {t('comms_intelligence.email_preview', { defaultValue: 'Email preview' })}
          </span>
          <span className="ml-auto flex items-center gap-1">
            <a href={emlDownloadUrl(correspondenceId)} target="_blank" rel="noreferrer">
              <Button size="sm" variant="ghost">
                <Download className="h-4 w-4" />
                {t('comms_intelligence.download_eml', { defaultValue: '.eml' })}
              </Button>
            </a>
            {bridgeQuery.data?.outlook_possible && (
              <Button size="sm" variant="secondary" onClick={() => outlookMut.mutate()} disabled={outlookMut.isPending}>
                {outlookMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                {t('comms_intelligence.open_outlook', { defaultValue: 'Open in Outlook' })}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </span>
        </div>
        <div className="border-b border-border-light p-3 text-sm">
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-tertiary">To</span>
            <span>{p ? p.to.join('; ') || '-' : '...'}</span>
          </div>
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-tertiary">Cc</span>
            <span>{p ? p.cc.join('; ') || '-' : '...'}</span>
          </div>
          <div className="flex gap-2">
            <span className="w-14 shrink-0 text-text-tertiary">Subject</span>
            <span className="font-medium">{p ? p.subject : '...'}</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span className="w-14 shrink-0 text-xs text-text-tertiary">
              {t('comms_intelligence.extra_to', { defaultValue: 'Add to' })}
            </span>
            <input
              className="w-full rounded border border-border-light bg-surface-primary px-2 py-1 text-xs"
              placeholder={t('comms_intelligence.extra_to_ph', { defaultValue: 'extra addresses, semicolon-separated' })}
              value={extraTo}
              onChange={(e) => setExtraTo(e.target.value)}
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-white">
          {previewQuery.isLoading ? (
            <div className="flex justify-center p-8">
              <Loader2 className="h-6 w-6 animate-spin text-text-tertiary" />
            </div>
          ) : (
            <iframe title="email-preview" className="h-[60vh] w-full border-0" srcDoc={p?.html ?? ''} />
          )}
        </div>
        <div className="border-t border-border-light p-2 text-center text-xs text-text-tertiary">
          {t('comms_intelligence.preview_note', {
            defaultValue: 'What you see is exactly what the draft carries. Sending always happens in your mail client.',
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outlook tab - inbox capture is disabled in this build
// ---------------------------------------------------------------------------

// Reading a mailbox (the inbox sweep) is deliberately not part of this build,
// so the tab is a greyed placeholder: it says capture is off and points at the
// way correspondence actually gets onto the register here - a reply filed by
// hand from a register item. Outgoing email is unaffected.
function OutlookTab(_props: { projectId: string }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-6 text-center opacity-80">
      <Mail className="mx-auto mb-2 h-6 w-6 text-text-tertiary" />
      <div className="text-sm font-semibold text-content-secondary">
        {t('comms_intelligence.outlook_disabled_title', {
          defaultValue: 'Inbox capture is off in this build',
        })}
      </div>
      <p className="mx-auto mt-1 max-w-md text-xs text-text-tertiary">
        {t('comms_intelligence.outlook_disabled_body', {
          defaultValue:
            'This build does not read a mailbox. Add a supplier reply to a register item by hand with "Attach a reply"; outgoing register emails still open as Outlook drafts or download as .eml.',
        })}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Draft card
// ---------------------------------------------------------------------------

function DraftCard({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const statusMut = useMutation({
    mutationFn: (status: 'accepted' | 'dismissed') => setDraftStatus(draft.id, status),
    onSuccess: (_d, status) => {
      addToast({
        type: 'info',
        title:
          status === 'accepted'
            ? t('comms_intelligence.toast.draft_accepted', { defaultValue: 'Draft marked as used' })
            : t('comms_intelligence.toast.draft_dismissed', { defaultValue: 'Draft dismissed' }),
      });
      onClose();
    },
  });

  const copy = () => {
    void navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`).then(() => {
      addToast({ type: 'success', title: t('comms_intelligence.toast.copied', { defaultValue: 'Draft copied to clipboard' }) });
    });
  };

  return (
    <div className="mt-3 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="flex items-center gap-2">
        <Badge variant={draft.source === 'ai' ? 'purple' : 'neutral'}>
          {draft.source === 'ai'
            ? t('comms_intelligence.draft_ai', { defaultValue: 'AI draft' })
            : t('comms_intelligence.draft_template', { defaultValue: 'template' })}
        </Badge>
        {draft.source === 'ai' && <ConfidenceBadge score={draft.confidence} showScore size="sm" />}
        <span className="text-sm font-medium">{draft.subject}</span>
        <span className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" onClick={copy}>
            <ClipboardCopy className="h-4 w-4" />
            {t('comms_intelligence.copy', { defaultValue: 'Copy' })}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => statusMut.mutate('accepted')}>
            {t('comms_intelligence.mark_used', { defaultValue: 'Mark used' })}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => statusMut.mutate('dismissed')}>
            <X className="h-4 w-4" />
          </Button>
        </span>
      </div>
      <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-text-secondary">{draft.body}</pre>
      <p className="mt-1 text-xs text-text-tertiary">
        {t('comms_intelligence.draft_note', {
          defaultValue: 'Copy this into your mail client to send - nothing is sent from here.',
        })}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deadlines table
// ---------------------------------------------------------------------------

function DeadlineTable({ title, entries, tone }: { title: string; entries: DashboardEntry[]; tone: 'error' | 'warning' | 'neutral' }) {
  const { t } = useTranslation();
  if (entries.length === 0) return null;
  return (
    <div className="rounded-lg border border-border-light bg-surface-primary p-3">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        {tone === 'error' && <AlertTriangle className="h-4 w-4 text-rose-500" />}
        {tone === 'warning' && <Clock className="h-4 w-4 text-amber-500" />}
        {title}
        <Badge variant={tone}>{entries.length}</Badge>
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-tertiary">
              <th className="py-1 pr-3">{t('comms_intelligence.col_ref', { defaultValue: 'Ref' })}</th>
              <th className="py-1 pr-3">{t('comms_intelligence.col_subject', { defaultValue: 'Subject' })}</th>
              <th className="py-1 pr-3">{t('comms_intelligence.col_category', { defaultValue: 'Category' })}</th>
              <th className="py-1 pr-3">{t('comms_intelligence.col_due', { defaultValue: 'Response due' })}</th>
              <th className="py-1">{t('comms_intelligence.col_days', { defaultValue: 'Days' })}</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.correspondence_id} className="border-t border-border-light/60">
                <td className="py-1.5 pr-3 font-mono">{e.reference_number}</td>
                <td className="max-w-md truncate py-1.5 pr-3">{e.subject}</td>
                <td className="py-1.5 pr-3">
                  <CategoryBadge category={e.category} />
                </td>
                <td className="py-1.5 pr-3">{e.response_required_by ?? '—'}</td>
                <td className={`py-1.5 tabular-nums ${e.days_until_due !== null && e.days_until_due < 0 ? 'font-semibold text-rose-600' : ''}`}>
                  {e.days_until_due ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type TabId = 'registers' | 'compare' | 'tracking' | 'review' | 'deadlines' | 'outlook';

export default function CommsIntelligenceModule() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const projectName = useProjectContextStore((s) => s.activeProjectName);
  const [tab, setTab] = useState<TabId>('registers');
  // The email flow lives at page level: rows, the drawer and the raise
  // form all open the same dialog.
  const [emailItem, setEmailItem] = useState<RegisterItemRow | null>(null);
  // Which item another tab asked us to open. Tracking rows used to name
  // an item and leave you to go and find it.
  const [focusItem, setFocusItem] = useState<{ id: string; kind: Kind } | null>(null);
  // Which package the compare tab should scroll to on arrival.
  const [compareFocus, setCompareFocus] = useState<string | null>(null);

  // DEEP LINKS. A chip on an RFI row, a PO row, a correspondence row or
  // the project hub lands here with ``?item=<id>`` (``&tab=compare`` for
  // a package) or ``?project=<id>``. The item names its own project, so
  // the workspace switches to it when needed, then opens the right tab on
  // the right row. Honoured once and then stripped from the address bar,
  // so a later tab switch is not fought by the URL.
  const [searchParams, setSearchParams] = useSearchParams();
  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const addToast = useToastStore((s) => s.addToast);
  const deepLinkDone = useRef(false);
  const navigate = useNavigate();
  const goMenu = useMenu();

  // Right-click on the page itself for a fast jump to the screens this
  // feeds - the standup's own list, mirrored. Anything with its own menu
  // (rows, steps, chips) has already claimed the event; text fields and
  // links keep the browser's menu.
  const pageMenu = (e: ReactMouseEvent) => {
    if (e.defaultPrevented || keepsNativeMenu(e.target)) return;
    if ((e.target as HTMLElement | null)?.closest?.('a[href], iframe')) return;
    goMenu.openFromEvent(
      e,
      [
        {
          label: t('comms_intelligence.go_standup', { defaultValue: 'Team Standup' }),
          note: t('comms_intelligence.go_standup_note', { defaultValue: 'the daily board' }),
          onClick: () => navigate('/team-standup'),
        },
        { label: t('comms_intelligence.go_rfi', { defaultValue: 'RFIs' }), onClick: () => navigate('/rfi') },
        { label: t('comms_intelligence.go_procurement', { defaultValue: 'Procurement' }), onClick: () => navigate('/procurement') },
        { label: t('comms_intelligence.go_bids', { defaultValue: 'Bid management' }), onClick: () => navigate('/bid-management') },
        null,
        projectId
          ? {
              label: t('comms_intelligence.go_project', { defaultValue: 'Project hub' }),
              note: projectName || undefined,
              onClick: () => navigate(`/projects/${encodeURIComponent(projectId)}`),
            }
          : null,
      ],
      { head: t('comms_intelligence.go_to', { defaultValue: 'Go to' }) },
    );
  };
  useEffect(() => {
    if (deepLinkDone.current) return;
    const itemParam = searchParams.get('item');
    const projectParam = searchParams.get('project');
    const tabParam = searchParams.get('tab');
    if (!itemParam && !projectParam) return;
    deepLinkDone.current = true;
    void (async () => {
      try {
        let target = projectParam;
        let item: RegisterItemRow | null = null;
        if (itemParam) {
          item = await fetchItem(itemParam);
          target = item.project_id;
        }
        if (target && target !== useProjectContextStore.getState().activeProjectId) {
          let name = '';
          try {
            name = (await apiGet<{ name?: string }>(`/v1/projects/${encodeURIComponent(target)}`)).name ?? '';
          } catch {
            // The switch still happens; the name fills in when the hub next loads it.
          }
          setActiveProject(target, name);
        }
        if (item) {
          if (tabParam === 'compare') {
            setCompareFocus(item.id);
            setTab('compare');
          } else {
            setFocusItem({ id: item.id, kind: item.kind });
            setTab('registers');
          }
        } else if (tabParam === 'compare' || tabParam === 'tracking' || tabParam === 'review' || tabParam === 'deadlines') {
          setTab(tabParam);
        }
      } catch {
        addToast({
          type: 'error',
          title: t('comms_intelligence.deep_link_missing', {
            defaultValue: 'That register item could not be found.',
          }),
        });
      } finally {
        setSearchParams(new URLSearchParams(), { replace: true });
      }
    })();
  }, [searchParams, setSearchParams, setActiveProject, addToast, t]);

  const dashboardQuery = useQuery<Dashboard>({
    queryKey: ['comms-intelligence', projectId, 'dashboard'],
    queryFn: () => fetchDashboard(projectId as string),
    enabled: !!projectId,
  });

  const suggestionsQuery = useQuery<Analysis[]>({
    queryKey: ['comms-intelligence', projectId, 'suggested'],
    queryFn: () => fetchAnalyses(projectId as string, 'suggested'),
    enabled: !!projectId,
  });

  // AUTO-REFRESH. Nothing on this page ever re-checked: the screen was
  // only as fresh as the last time somebody clicked Refresh, so a reply
  // that arrived two hours ago still read as "waiting on them". The old
  // app polled every 45 seconds and said what it had done; this does the
  // same, and shows when it last looked so "nothing new" is legible as
  // an answer rather than as a stuck screen.
  const REFRESH_MS = 45_000;
  const [lastChecked, setLastChecked] = useState<number>(() => Date.now());
  const [tick, setTick] = useState(0);
  // WATCHING OUTLOOK is opt-in and remembered. The sweep shells out to
  // Outlook over COM, so it is a real cost on the machine rather than a
  // cheap fetch - it should be a thing you switched on, not a thing that
  // started happening to you.
  useEffect(() => {
    if (!projectId) return;
    const id = window.setInterval(() => {
      // Only when the tab is actually being looked at. Polling a
      // backgrounded tab every 45s all afternoon is a battery bill and a
      // pile of Outlook COM calls nobody is reading.
      if (document.visibilityState !== 'visible') return;
      void queryClient.invalidateQueries({ queryKey: ['comms-intelligence', projectId] });
      void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
      setLastChecked(Date.now());
      // Deadlines onto the bus. Failure here is silent on purpose: the
      // bell not ringing must never look like the page being broken.
      void deadlineSweep(projectId).catch(() => undefined);
    }, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [projectId, queryClient]);
  // Re-render once a second so the "checked Ns ago" line counts up
  // instead of freezing at whatever it said when the data last changed.
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  void tick; // read so the 1s interval above is not dead state
  const secondsAgo = Math.max(0, Math.round((Date.now() - lastChecked) / 1000));

  const dash = dashboardQuery.data;
  const suggestions = useMemo(() => suggestionsQuery.data ?? [], [suggestionsQuery.data]);

  if (!projectId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<Inbox className="h-8 w-8" />}
          title={t('comms_intelligence.no_project_title', { defaultValue: 'Pick a project first' })}
          description={t('comms_intelligence.no_project_desc', {
            defaultValue: 'Comms Intelligence works on one project’s correspondence register at a time.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4" onContextMenu={pageMenu}>
      {goMenu.element}
      <DismissibleInfo
        storageKey="comms-intelligence-intro"
        title={t('comms_intelligence.intro_title', { defaultValue: 'Smarts over the correspondence register' })}
      >
        {t('comms_intelligence.intro_text', {
          defaultValue:
            'Every inbound message is classified and mined for prices, quote numbers, deadlines and commitments the moment it lands. Nothing changes on a record until you confirm the suggestion - AI-augmented, human-confirmed.',
        })}
      </DismissibleInfo>

      {/* ONE FIXED BAND, PINNED. It used to render on only two of the six
          tabs and scroll away with the content, so the numbers you steer
          by moved or vanished depending on where you were standing. Now
          the band and the strip are one sticky header: same figures, same
          place, whatever tab is open. Each tile is a drill-down into the
          tab that explains it. */}
      <div className="sticky top-0 z-30 -mx-4 space-y-3 border-b border-border bg-surface-primary/95 px-4 pb-0 pt-3 backdrop-blur">
        <KpiBand
          columns={4}
          size="sm"
          items={[
            {
              key: 'pending',
              label: t('comms_intelligence.kpi_pending', { defaultValue: 'Pending review' }),
              value: dash?.pending_review ?? '—',
              icon: Inbox,
              tone: 'blue',
              onClick: () => setTab('review'),
              ariaLabel: t('comms_intelligence.kpi_pending_go', {
                defaultValue: 'Pending review - open the review queue',
              }),
            },
            {
              key: 'reply',
              label: t('comms_intelligence.kpi_reply', { defaultValue: 'Reply needed' }),
              value: dash?.reply_needed ?? '—',
              icon: MailQuestion,
              tone: 'warning',
              onClick: () => setTab('tracking'),
              ariaLabel: t('comms_intelligence.kpi_reply_go', {
                defaultValue: 'Reply needed - open email tracking',
              }),
            },
            {
              key: 'overdue',
              label: t('comms_intelligence.kpi_overdue', { defaultValue: 'Overdue responses' }),
              value: dash?.overdue.length ?? '—',
              icon: AlertTriangle,
              tone: 'danger',
              tintValue: (dash?.overdue.length ?? 0) > 0,
              onClick: () => setTab('deadlines'),
              ariaLabel: t('comms_intelligence.kpi_overdue_go', {
                defaultValue: 'Overdue responses - open deadlines',
              }),
            },
            {
              key: 'due_soon',
              label: t('comms_intelligence.kpi_due_soon', { defaultValue: 'Due within 3 days' }),
              value: dash?.due_soon.length ?? '—',
              icon: Clock,
              tone: 'warning',
              onClick: () => setTab('deadlines'),
              ariaLabel: t('comms_intelligence.kpi_due_soon_go', {
                defaultValue: 'Due within three days - open deadlines',
              }),
            },
          ]}
        />

        <div className="flex items-end gap-2">
          {/* The platform's own tab strip: role=tablist, arrow-key
              navigation, badge slots and the --oe-blue active colour every
              other module uses. What it replaces was a row of plain
              buttons - a screen reader announced six buttons and nothing
              said which one you were standing on. */}
          <TabBar
            className="min-w-0 flex-1"
            ariaLabel={t('comms_intelligence.tabs_aria', { defaultValue: 'Comms Intelligence sections' })}
            activeId={tab}
            onChange={setTab}
            idPrefix="comms-intelligence"
            tabs={[
              {
                id: 'registers' as TabId,
                label: t('comms_intelligence.tab_registers', { defaultValue: 'Registers' }),
                icon: <ClipboardList className="h-4 w-4" />,
              },
              {
                id: 'compare' as TabId,
                label: t('comms_intelligence.tab_compare', { defaultValue: 'Compare & award' }),
                icon: <Scale className="h-4 w-4" />,
              },
              {
                id: 'tracking' as TabId,
                label: t('comms_intelligence.tab_tracking', { defaultValue: 'Email tracking' }),
                icon: <Send className="h-4 w-4" />,
                badge: dash?.reply_needed ? (
                  <Badge variant="warning" size="sm">
                    {dash.reply_needed}
                  </Badge>
                ) : undefined,
              },
              {
                id: 'review' as TabId,
                label: t('comms_intelligence.tab_review', { defaultValue: 'Review queue' }),
                icon: <Inbox className="h-4 w-4" />,
                badge: dash?.pending_review ? (
                  <Badge variant="blue" size="sm">
                    {dash.pending_review}
                  </Badge>
                ) : undefined,
              },
              {
                id: 'deadlines' as TabId,
                label: t('comms_intelligence.tab_deadlines', { defaultValue: 'Deadlines' }),
                icon: <Clock className="h-4 w-4" />,
                badge: dash?.overdue.length ? (
                  <Badge variant="error" size="sm">
                    {dash.overdue.length}
                  </Badge>
                ) : undefined,
              },
              {
                id: 'outlook' as TabId,
                label: t('comms_intelligence.tab_outlook', { defaultValue: 'Outlook' }),
                icon: <Mail className="h-4 w-4" />,
                // Greyed out: inbox capture (reading a mailbox) is not part of
                // this build, so the tab is present but disabled.
                disabled: true,
              },
            ]}
          />
          <span className="mb-1 shrink-0 whitespace-nowrap text-[11px] text-content-tertiary">
            {secondsAgo < 60
              ? t('comms_intelligence.checked_secs', {
                  defaultValue: 'checked {{n}}s ago',
                  n: secondsAgo,
                })
              : t('comms_intelligence.checked_mins', {
                  defaultValue: 'checked {{n}}m ago',
                  n: Math.floor(secondsAgo / 60),
                })}
          </span>
          <Button
            size="sm"
            variant="ghost"
            className="mb-1 shrink-0"
            title={t('comms_intelligence.refresh_hint', {
              defaultValue: 'Checks by itself every 45 seconds while this tab is open',
            })}
            onClick={() => {
              void queryClient.invalidateQueries({ queryKey: ['comms-intelligence', projectId] });
              void queryClient.invalidateQueries({ queryKey: ['registers', projectId] });
              setLastChecked(Date.now());
            }}
          >
            <RefreshCw className="h-4 w-4" />
            {t('comms_intelligence.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>
      </div>

      {tab === 'review' &&
        (suggestionsQuery.isLoading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="h-6 w-6 animate-spin text-text-tertiary" />
          </div>
        ) : suggestions.length === 0 ? (
          <EmptyState
            icon={<CheckCheck className="h-8 w-8" />}
            title={t('comms_intelligence.queue_empty_title', { defaultValue: 'Review queue is clear' })}
            description={t('comms_intelligence.queue_empty_desc', {
              defaultValue:
                'New incoming correspondence is analysed automatically and lands here for your confirmation.',
            })}
          />
        ) : (
          <div className="space-y-2">
            {suggestions.map((a) => (
              <AnalysisRow key={a.id} analysis={a} projectId={projectId} />
            ))}
          </div>
        ))}

      {tab === 'registers' && (
        <RegisterWorkspace
          onEmailItem={setEmailItem}
          focus={focusItem}
          onOpenCompare={(id) => {
            setCompareFocus(id);
            setTab('compare');
          }}
          onOpenTracking={() => setTab('tracking')}
        />
      )}

      {tab === 'compare' && <ComparePanel projectId={projectId} focusItemId={compareFocus} />}

      {tab === 'tracking' && (
        <TrackingTab
          projectId={projectId}
          onOpenItem={(id, kind) => {
            setFocusItem({ id, kind });
            setTab('registers');
          }}
          // Chasing is just the item's own email with the send log
          // already on it, so it reuses the one dialog rather than
          // inventing a second way to write to the same supplier.
          onChase={(id, kind) => {
            setFocusItem({ id, kind });
            setTab('registers');
          }}
        />
      )}
      {tab === 'outlook' && <OutlookTab projectId={projectId} />}

      {emailItem && (
        <RegisterEmailDialog item={emailItem} projectId={projectId} onClose={() => setEmailItem(null)} />
      )}

      {tab === 'deadlines' && dash && (
        <div className="space-y-3">
          <DeadlineTable
            title={t('comms_intelligence.overdue_title', { defaultValue: 'Overdue' })}
            entries={dash.overdue}
            tone="error"
          />
          <DeadlineTable
            title={t('comms_intelligence.due_soon_title', { defaultValue: 'Due soon' })}
            entries={dash.due_soon}
            tone="warning"
          />
          <DeadlineTable
            title={t('comms_intelligence.awaiting_title', { defaultValue: 'Awaiting response (no deadline)' })}
            entries={dash.awaiting_response}
            tone="neutral"
          />
          {dash.overdue.length === 0 && dash.due_soon.length === 0 && dash.awaiting_response.length === 0 && (
            <EmptyState
              icon={<CheckCheck className="h-8 w-8" />}
              title={t('comms_intelligence.deadlines_empty', { defaultValue: 'Nothing is owed either way' })}
              description={t('comms_intelligence.deadlines_empty_desc', {
                defaultValue: `No open correspondence on ${projectName || 'this project'} is waiting on a response.`,
              })}
            />
          )}
        </div>
      )}
    </div>
  );
}
