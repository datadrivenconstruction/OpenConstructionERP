// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet completeness panel (item #46).
 *
 * Reconciles the project's uploaded sheets against a drawing index / issue
 * register and shows the gaps with the shared traffic-light vocabulary:
 * missing sheets (red), extra sheets and revision mismatches (amber). The index
 * source is either an already-uploaded index PDF or a pasted sheet list. The
 * run persists a document validation report, so the newest result is restored
 * on mount and the findings can be exported (server-rendered, injection-safe).
 *
 * Surface-agnostic: it takes only a `projectId` (and an optional default index
 * document), so it drops into the Plan Room, the Sheets index page or the
 * Validation page unchanged. `embedded` drops its own card and heading for a
 * host that already titles the section (the Plan Room disclosure).
 */

import { type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, ClipboardCheck, Download, GitBranch, XCircle } from 'lucide-react';
import { apiGet, getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { Badge, Button, Card, EmptyState, SkeletonText } from '@/shared/ui';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { validationExportFilename, validationExportPath } from '../validation/validationExport';
import { fetchPlanRoomDrawings } from './api';
import {
  checkSheetCompleteness,
  type SheetCompletenessRequest,
  type SheetCompletenessSummary,
  type StoredValidationReport,
} from './sheetCompleteness';

interface SheetCompletenessPanelProps {
  projectId: string;
  /** Pre-select this document as the index source (e.g. the open drawing). */
  defaultIndexDocumentId?: string;
  /** Render without the card and heading, inside a host section that has them. */
  embedded?: boolean;
}

interface PanelResult {
  summary: SheetCompletenessSummary;
  reportId: string;
  status: string;
  score: number | null;
}

type Mode = 'document' | 'paste';

export function SheetCompletenessPanel({
  projectId,
  defaultIndexDocumentId,
  embedded = false,
}: SheetCompletenessPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [mode, setMode] = useState<Mode>('document');
  const [indexDocId, setIndexDocId] = useState(defaultIndexDocumentId ?? '');
  const [indexPage, setIndexPage] = useState('');
  const [pastedText, setPastedText] = useState('');
  const [result, setResult] = useState<PanelResult | null>(null);
  const [exportPending, setExportPending] = useState(false);

  // Adopt the open drawing as the index default until the user picks their own.
  useEffect(() => {
    if (defaultIndexDocumentId && !indexDocId) setIndexDocId(defaultIndexDocumentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaultIndexDocumentId]);

  const { data: drawings = [] } = useQuery({
    queryKey: ['plan-room-drawings', projectId],
    queryFn: () => fetchPlanRoomDrawings(projectId),
    enabled: !!projectId,
  });

  const latestQuery = useQuery({
    queryKey: ['sheet-completeness', 'latest', projectId],
    queryFn: () =>
      apiGet<StoredValidationReport[]>(
        `/v1/validation/reports/?project_id=${projectId}&target_type=document&limit=50`,
      ),
    enabled: !!projectId,
  });

  // Restore the newest stored completeness report once, so a re-open shows the
  // last result without re-running. A fresh run (below) then wins.
  useEffect(() => {
    if (result || !latestQuery.data) return;
    const latest = latestQuery.data.find(
      (r) => r.rule_set === 'sheet_completeness' && r.metadata?.sheet_completeness,
    );
    const snapshot = latest?.metadata?.sheet_completeness;
    if (latest && snapshot) {
      setResult({
        summary: snapshot,
        reportId: latest.id,
        status: latest.status,
        score: latest.score ? Number(latest.score) : null,
      });
    }
  }, [latestQuery.data, result]);

  const mutation = useMutation({
    mutationFn: (body: SheetCompletenessRequest) => checkSheetCompleteness(body),
    onSuccess: (res) => {
      setResult({ summary: res.completeness, reportId: res.report_id, status: res.status, score: res.score });
      qc.invalidateQueries({ queryKey: ['sheet-completeness'] });
      qc.invalidateQueries({ queryKey: ['validation'] });
      addToast({
        type: 'success',
        title: t('sheetCompleteness.done', { defaultValue: 'Completeness check complete' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('sheetCompleteness.error_title', { defaultValue: 'Completeness check failed' }),
        message: getErrorMessage(err),
      });
    },
  });

  const hasSource = mode === 'document' ? !!indexDocId : !!pastedText.trim();

  const runCheck = () => {
    if (!hasSource || mutation.isPending) return;
    const body: SheetCompletenessRequest = { project_id: projectId, current_only: true };
    if (mode === 'document') {
      body.index_document_id = indexDocId;
      const pageNum = Number.parseInt(indexPage, 10);
      if (Number.isFinite(pageNum) && pageNum >= 1) body.index_page = pageNum;
    } else {
      body.pasted_index = pastedText;
    }
    mutation.mutate(body);
  };

  const handleExport = async () => {
    if (!result?.reportId || exportPending) return;
    setExportPending(true);
    try {
      const token = useAuthStore.getState().accessToken;
      const resp = await fetch(validationExportPath(result.reportId, 'xlsx'), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
      const blob = await resp.blob();
      triggerDownload(blob, validationExportFilename('xlsx', { reportId: result.reportId }));
    } catch (err) {
      addToast({
        type: 'error',
        title: t('sheetCompleteness.export_failed', { defaultValue: 'Export failed' }),
        message: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setExportPending(false);
    }
  };

  const summary = result?.summary ?? null;
  const allPresent =
    !!summary &&
    summary.missing.length === 0 &&
    summary.extra.length === 0 &&
    summary.rev_mismatch.length === 0;

  const body = (
    <>
      {/* Index source */}
      <div className={embedded ? 'max-w-md space-y-2' : 'mt-3 space-y-2'}>
        <div className="flex gap-1.5">
          <Button
            variant={mode === 'document' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setMode('document')}
          >
            {t('sheetCompleteness.mode_document', { defaultValue: 'From an index PDF' })}
          </Button>
          <Button
            variant={mode === 'paste' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setMode('paste')}
          >
            {t('sheetCompleteness.mode_paste', { defaultValue: 'Paste a sheet list' })}
          </Button>
        </div>

        {mode === 'document' ? (
          <div className="space-y-2">
            <label className="block text-2xs font-medium text-content-tertiary">
              {t('sheetCompleteness.pick_index', { defaultValue: 'Index drawing' })}
              <select
                value={indexDocId}
                onChange={(e) => setIndexDocId(e.target.value)}
                className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
              >
                <option value="">
                  {t('sheetCompleteness.pick_index_placeholder', { defaultValue: 'Choose a drawing…' })}
                </option>
                {drawings.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename || d.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-2xs font-medium text-content-tertiary">
              {t('sheetCompleteness.index_page', { defaultValue: 'Index page (optional)' })}
              <input
                type="number"
                min={1}
                value={indexPage}
                onChange={(e) => setIndexPage(e.target.value)}
                placeholder={t('sheetCompleteness.index_page_placeholder', { defaultValue: 'All pages' })}
                className="mt-1 w-full rounded-lg border border-border bg-surface-primary px-2 py-1.5 text-sm text-content-primary"
              />
            </label>
          </div>
        ) : (
          <textarea
            value={pastedText}
            onChange={(e) => setPastedText(e.target.value)}
            rows={5}
            placeholder={t('sheetCompleteness.paste_placeholder', {
              defaultValue: 'One sheet per line, or number,title,rev',
            })}
            className="w-full rounded-lg border border-border bg-surface-primary px-2 py-1.5 font-mono text-xs text-content-primary"
          />
        )}

        <Button
          variant="primary"
          size="sm"
          className="w-full"
          loading={mutation.isPending}
          disabled={!hasSource}
          onClick={runCheck}
        >
          {mutation.isPending
            ? t('sheetCompleteness.running', { defaultValue: 'Checking…' })
            : t('sheetCompleteness.run', { defaultValue: 'Run completeness check' })}
        </Button>
        {!hasSource && (
          <p className="text-2xs text-content-quaternary">
            {t('sheetCompleteness.no_index', { defaultValue: 'Choose an index source first' })}
          </p>
        )}
      </div>

      {/* Result */}
      <div className="mt-3">
        {mutation.isPending ? (
          <SkeletonText lines={3} />
        ) : summary ? (
          <SheetCompletenessResult
            summary={summary}
            allPresent={allPresent}
            score={result?.score ?? null}
            exportPending={exportPending}
            onExport={handleExport}
          />
        ) : (
          <EmptyState
            icon={<ClipboardCheck size={22} />}
            title={t('sheetCompleteness.empty_title', { defaultValue: 'No completeness check yet' })}
            description={t('sheetCompleteness.empty_desc', {
              defaultValue: 'Pick the drawing index (or paste the sheet list) and run the check.',
            })}
          />
        )}
      </div>
    </>
  );

  if (embedded) return <div>{body}</div>;

  return (
    <Card padding="md">
      <div className="flex items-start gap-2">
        <ClipboardCheck size={16} className="mt-0.5 shrink-0 text-content-tertiary" />
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('sheetCompleteness.title', { defaultValue: 'Sheet completeness' })}
          </h3>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {t('sheetCompleteness.subtitle', {
              defaultValue: 'Reconcile the drawing index / issue register against the uploaded sheets',
            })}
          </p>
        </div>
      </div>
      {body}
    </Card>
  );
}

/* ── Result block ────────────────────────────────────────────────────────── */

function SheetCompletenessResult({
  summary,
  allPresent,
  score,
  exportPending,
  onExport,
}: {
  summary: SheetCompletenessSummary;
  allPresent: boolean;
  score: number | null;
  exportPending: boolean;
  onExport: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-2xs text-content-tertiary">
          {t('sheetCompleteness.matched', {
            defaultValue: '{{matched}} of {{expected}} matched',
            matched: summary.matched.length,
            expected: summary.expected_count,
          })}
        </span>
        {score !== null && (
          <Badge variant={allPresent ? 'success' : 'warning'} size="sm">
            {Math.round(score * 100)}%
          </Badge>
        )}
      </div>

      {allPresent ? (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-sm text-emerald-700 dark:text-emerald-300">
          <CheckCircle2 size={16} className="shrink-0" />
          {t('sheetCompleteness.all_present', {
            defaultValue: 'All {{count}} index sheets are present',
            count: summary.expected_count,
          })}
        </div>
      ) : (
        <div className="space-y-3">
          <FindingGroup
            icon={<XCircle size={14} className="text-red-500" />}
            title={t('sheetCompleteness.missing', { defaultValue: 'Missing from the set' })}
            items={summary.missing}
          />
          <FindingGroup
            icon={<AlertTriangle size={14} className="text-amber-500" />}
            title={t('sheetCompleteness.extra', { defaultValue: 'Not in the index' })}
            items={summary.extra}
          />
          {summary.rev_mismatch.length > 0 && (
            <div>
              <h4 className="mb-1.5 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                <GitBranch size={14} className="text-amber-500" />
                {t('sheetCompleteness.rev_mismatch', { defaultValue: 'Revision mismatch' })}
                <span className="text-content-quaternary">({summary.rev_mismatch.length})</span>
              </h4>
              <ul className="space-y-1">
                {summary.rev_mismatch.map((m) => (
                  <li key={m.sheet_number} className="flex items-center justify-between gap-2 text-sm">
                    <span className="font-medium text-content-secondary">{m.sheet_number}</span>
                    <span className="text-2xs text-content-tertiary">
                      {t('sheetCompleteness.rev_line', {
                        defaultValue: 'expected {{expected}} → set has {{actual}}',
                        expected: m.expected_rev,
                        actual: m.actual_rev,
                      })}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <Button variant="ghost" size="sm" loading={exportPending} onClick={onExport}>
        <Download size={14} className="mr-1.5" />
        {t('sheetCompleteness.export', { defaultValue: 'Export findings' })}
      </Button>
    </div>
  );
}

function FindingGroup({ icon, title, items }: { icon: ReactNode; title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="mb-1.5 flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
        {icon}
        {title}
        <span className="text-content-quaternary">({items.length})</span>
      </h4>
      <ul className="flex flex-wrap gap-1">
        {items.map((num) => (
          <li
            key={num}
            className="rounded-md border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs text-content-secondary"
          >
            {num}
          </li>
        ))}
      </ul>
    </div>
  );
}
