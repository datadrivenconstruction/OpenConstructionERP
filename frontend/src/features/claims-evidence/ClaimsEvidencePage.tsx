// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <ClaimsEvidencePage> - the project-wide evidence register.
//
// Where the provability gauge and the evidence-thread panel work on ONE change
// (mounted on a variation / change-order / MoC detail screen), this page is the
// module's home: it assembles the whole project's deterministic evidence pack -
// every change-family record plus the recent cross-module activity, ordered,
// sectioned and SHA-256 digested by the engine - and lets a commercial manager
// file it under a claim basis and export it. The same project state always
// yields the same pack and digest, so an export is reproducible for a claim.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { AlertTriangle, Download, Layers, ShieldCheck } from 'lucide-react';
import { Card, Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { fmtDate } from '@/shared/lib/formatters';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getEvidencePack } from './api';
import type { EvidencePack } from './types';

interface ProjectLite {
  id: string;
  name: string;
}

// The bases a pack can be filed under. The value is the string the engine files
// the pack against; the label is localized. Kept small and construction-claim
// oriented rather than exhaustive.
const BASES = ['dispute', 'valuation', 'delay', 'general'] as const;
type Basis = (typeof BASES)[number];

/** Best-effort title-case of a token like "change_order". */
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
 * Download the assembled pack as pretty-printed JSON. Guarded so an environment
 * without Blob / URL support simply does nothing rather than throwing.
 */
function downloadPack(pack: EvidencePack, projectName: string): void {
  try {
    const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    const slug = (projectName || 'project').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    anchor.download = `evidence-pack-${slug || 'project'}-${pack.basis}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  } catch {
    // Export is best-effort; ignore environments without Blob / URL support.
  }
}

export function ClaimsEvidencePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [basis, setBasis] = useState<Basis>('dispute');

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectLite[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = useMemo(
    () => projects.find((p) => p.id === projectId)?.name || '',
    [projects, projectId],
  );

  const q = useQuery({
    queryKey: ['claims-evidence', 'pack', projectId, basis],
    queryFn: () => getEvidencePack(projectId, projectName || 'project', basis),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const pack = q.data;
  const hasEntries = !!pack && pack.entry_count > 0;

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('claims_evidence.title', { defaultValue: 'Claims Evidence' })}
        subtitle={t('claims_evidence.subtitle', {
          defaultValue:
            'Assemble a reproducible evidence pack for a claim or dispute from the whole project record',
        })}
        actions={
          <button
            type="button"
            onClick={() => pack && downloadPack(pack, projectName)}
            disabled={!hasEntries}
            className="inline-flex items-center gap-1.5 rounded-md border border-border-light px-3 py-1.5 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {t('claims_evidence.export', { defaultValue: 'Export pack' })}
          </button>
        }
      />

      {!projectId ? (
        <Card className="p-6">
          <EmptyState
            icon={<ShieldCheck className="h-6 w-6" />}
            title={t('claims_evidence.select_project_title', { defaultValue: 'No project selected' })}
            description={t('claims_evidence.select_project_desc', {
              defaultValue: 'Open a project to assemble and export its evidence pack.',
            })}
          />
        </Card>
      ) : (
        <>
          <Card className="space-y-3 p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue">
                <ShieldCheck className="h-5 w-5" />
              </span>
              <p className="text-sm text-content-secondary">
                {t('claims_evidence.intro', {
                  defaultValue:
                    'Every notice, variation, change order, management-of-change entry and logged activity on this project, ordered and grouped into one deterministic pack with a content digest. File it under the basis you are building and export it to travel with a claim.',
                })}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t border-border-light pt-3">
              <label htmlFor="claims-evidence-basis" className="text-xs font-medium text-content-tertiary">
                {t('claims_evidence.basis_label', { defaultValue: 'Basis' })}
              </label>
              <select
                id="claims-evidence-basis"
                value={basis}
                onChange={(e) => setBasis(e.target.value as Basis)}
                className="rounded-md border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
              >
                {BASES.map((b) => (
                  <option key={b} value={b}>
                    {t(`claims_evidence.basis.${b}`, { defaultValue: humanize(b) })}
                  </option>
                ))}
              </select>
            </div>
          </Card>

          {q.isLoading ? (
            <Card className="p-4">
              <SkeletonTable />
            </Card>
          ) : q.isError ? (
            <Card className="p-4">
              <div className="flex items-center gap-2 text-sm text-semantic-error">
                <AlertTriangle className="h-4 w-4" />
                <span>{getErrorMessage(q.error) || t('claims_evidence.load_error', { defaultValue: 'Could not assemble the evidence pack.' })}</span>
              </div>
            </Card>
          ) : !hasEntries ? (
            <Card className="p-6">
              <EmptyState
                icon={<Layers className="h-6 w-6" />}
                title={t('claims_evidence.empty_title', { defaultValue: 'No evidence yet' })}
                description={t('claims_evidence.empty_desc', {
                  defaultValue:
                    'As notices, changes, correspondence and daily records accumulate they are threaded into the evidence pack here.',
                })}
              />
            </Card>
          ) : (
            <Card className="space-y-4 p-4">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-tertiary">
                <span>
                  {t('claims_evidence.records', {
                    defaultValue: '{{count}} record(s)',
                    count: pack.entry_count,
                  })}
                </span>
                {pack.date_from ? (
                  <span className="tabular-nums">
                    {formatDate(pack.date_from)} - {formatDate(pack.date_to)}
                  </span>
                ) : null}
                <span className="font-mono">
                  {t('claims_evidence.digest', { defaultValue: 'Digest' })}: {pack.content_digest.slice(0, 12)}
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
            </Card>
          )}
        </>
      )}
    </div>
  );
}

export default ClaimsEvidencePage;
