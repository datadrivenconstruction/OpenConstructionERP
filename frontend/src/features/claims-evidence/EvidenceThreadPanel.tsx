// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <EvidenceThreadPanel> - reconstruct one change as a scoped evidence thread (#16).
//
// A self-contained panel over the claims-evidence reconstruct endpoint. Where the
// provability gauge grades a single change, this grows the cross-channel thread
// around it (the reconciliation engine's connected component of linked records)
// and lays the records out by section, with a content digest and a one-click JSON
// export so the assembled pack can travel with a claim. The pack is reproducible:
// the same project state always yields the same digest.
//
// The fetch is deferred behind an explicit action so opening a change row does not
// build the whole project's reconciliation graph until the user asks for it. Mount
// it wherever a single change is on screen and pass the project id, the reconciled
// subject type and the subject id.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileStack, Layers } from 'lucide-react';
import { Card, Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { DocumentExportMenu, type DocumentExportItem } from '@/shared/ui/DocumentExportMenu';
import { fmtDate } from '@/shared/lib/formatters';
import {
  downloadReconstructedPack,
  exportReconstructedPack,
  reconstructChange,
  type ReconstructSubjectType,
} from './api';
import type { EvidencePack } from './types';

/** Best-effort title-case of a token like "variation_order". */
function humanize(token: string): string {
  return (token || '')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/** Locale-aware date for a pack timestamp, via the app-wide formatter. */
function formatDate(iso: string | null): string {
  if (!iso) return '';
  try {
    return fmtDate(iso);
  } catch {
    return iso;
  }
}

/**
 * Download the assembled pack as pretty-printed JSON. A convenience for taking a
 * reproducible evidence thread off-platform; guarded so an environment without
 * Blob / URL support (a test runner) simply does nothing rather than throwing.
 */
function downloadPack(pack: EvidencePack, subjectType: string, subjectId: string): void {
  try {
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `evidence-thread-${subjectType}-${subjectId}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  } catch {
    // Export is best-effort; ignore environments without Blob / URL support.
  }
}

export interface EvidenceThreadPanelProps {
  projectId: string;
  subjectType: ReconstructSubjectType;
  subjectId: string;
  /** Optional extra classes for the outer card. */
  className?: string;
}

/**
 * Reconstruct-this-change evidence thread for one subject.
 *
 * Renders an action that, once triggered, fetches and lays out the reconciled
 * pack by section with its digest and a JSON export. A host that has not selected
 * a subject should simply not render this component.
 */
export function EvidenceThreadPanel({ projectId, subjectType, subjectId, className }: EvidenceThreadPanelProps) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const q = useQuery({
    queryKey: ['claims-evidence', 'reconstruct', projectId, subjectType, subjectId],
    queryFn: () => reconstructChange(projectId, subjectType, subjectId),
    enabled: loaded && !!projectId && !!subjectType && !!subjectId,
    retry: false,
    staleTime: 30_000,
  });
  const pack = q.data;

  // The thread as a document for the claim file, or as data. Whichever is
  // taken, recording the export is the "assemble an evidence pack" adoption
  // action and lands it in the audit trail. It is best-effort and must never
  // block taking the pack off-platform, so it is fired and not awaited.
  const exportItems = useMemo<DocumentExportItem[]>(() => {
    const record = () => void exportReconstructedPack(projectId, subjectType, subjectId).catch(() => {});
    return [
      {
        id: 'pdf',
        label: t('doc_export.as_pdf', { defaultValue: 'PDF document' }),
        kind: 'pdf',
        run: (locale) => {
          record();
          return downloadReconstructedPack(projectId, subjectType, subjectId, 'pdf', locale);
        },
      },
      {
        id: 'xlsx',
        label: t('doc_export.as_xlsx', { defaultValue: 'Excel workbook (.xlsx)' }),
        kind: 'xlsx',
        run: (locale) => {
          record();
          return downloadReconstructedPack(projectId, subjectType, subjectId, 'xlsx', locale);
        },
      },
      {
        id: 'json',
        label: t('claims_evidence.export_json', { defaultValue: 'JSON data file' }),
        kind: 'other',
        run: () => {
          record();
          if (pack) downloadPack(pack, subjectType, subjectId);
        },
      },
    ];
  }, [projectId, subjectType, subjectId, pack, t]);

  return (
    <Card className={`space-y-3 p-4 ${className ?? ''}`}>
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
          <Layers className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('reconstruct.title', { defaultValue: 'Evidence thread' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('reconstruct.subtitle', {
              defaultValue: 'The reconciled record of this change, ready to export',
            })}
          </p>
        </div>
        {pack && pack.entry_count > 0 ? (
          <DocumentExportMenu
            label={t('reconstruct.export', { defaultValue: 'Export' })}
            items={exportItems}
            className="ml-auto"
            testId="evidence-thread-export"
          />
        ) : null}
      </div>

      {!loaded ? (
        <button
          type="button"
          onClick={() => setLoaded(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-sm font-medium text-white hover:bg-oe-blue-hover"
        >
          <FileStack className="h-4 w-4" />
          {t('reconstruct.action', { defaultValue: 'Reconstruct evidence thread' })}
        </button>
      ) : q.isLoading ? (
        <SkeletonTable />
      ) : q.isError ? (
        <div className="flex items-center gap-2 text-sm text-semantic-error">
          <AlertTriangle className="h-4 w-4" />
          <span>{getErrorMessage(q.error)}</span>
        </div>
      ) : !pack || pack.entry_count === 0 ? (
        <EmptyState
          icon={<Layers className="h-6 w-6" />}
          title={t('reconstruct.empty_title', { defaultValue: 'Nothing linked yet' })}
          description={t('reconstruct.empty_desc', {
            defaultValue:
              'No records are reconciled to this change yet. As correspondence, notices and orders accumulate they will be threaded here.',
          })}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-tertiary">
            <span>
              {t('reconstruct.entry_count', {
                defaultValue: '{{count}} linked record(s)',
                count: pack.entry_count,
              })}
            </span>
            {pack.date_from ? (
              <span className="tabular-nums">
                {formatDate(pack.date_from)} - {formatDate(pack.date_to)}
              </span>
            ) : null}
            <span className="font-mono">
              {t('reconstruct.digest', { defaultValue: 'Digest' })}: {pack.content_digest.slice(0, 12)}
            </span>
          </div>
          {pack.sections.map((section) => (
            <div key={section.name} className="space-y-1.5">
              <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {/* Engine section / kind tokens are stable: translate them by
                    token and let an unknown one fall back to a humanized form. */}
                {t(`claims_evidence.section.${section.name}`, { defaultValue: humanize(section.name) })}
              </div>
              <ul className="space-y-1">
                {section.entries.map((entry) => (
                  <li key={entry.ref_id} className="flex items-start gap-2 text-sm">
                    <Badge variant="neutral">
                      {t(`claims_evidence.kind.${entry.kind}`, { defaultValue: humanize(entry.kind) })}
                    </Badge>
                    <span className="min-w-0 flex-1 text-content-secondary">
                      {entry.title || t(`claims_evidence.kind.${entry.kind}`, { defaultValue: humanize(entry.kind) })}
                    </span>
                    {entry.occurred_at ? (
                      <span className="shrink-0 tabular-nums text-xs text-content-tertiary">
                        {formatDate(entry.occurred_at)}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default EvidenceThreadPanel;
