// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Checks": the open validation findings of what is on screen, with a
 * counter, as a side sheet that never blocks the page. On a bill it reads the
 * bill's latest stored validation report; other pages publish their own
 * findings through `publishChecks`. Findings are also marked on their rows
 * and fields in place (shared/lib/checks.ts).
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, matchPath, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ListChecks, X } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import {
  countBySeverity,
  elementsFor,
  markFindings,
  openFindings,
  useChecksStore,
  type CheckFinding,
  type CheckSeverity,
} from '@/shared/lib/checks';

interface StoredRow {
  rule_id: string;
  rule_name?: string;
  severity?: string;
  status?: string;
  passed?: boolean;
  message: string;
  element_ref?: string | null;
  suggestion?: string | null;
}

interface StoredReport {
  id: string;
  target_id: string;
  results: StoredRow[];
}

function toSeverity(value: string | undefined): CheckSeverity {
  if (value === 'error') return 'error';
  if (value === 'info') return 'info';
  return 'warning';
}

function useBillReport(boqId: string | null) {
  const boq = useQuery({
    queryKey: ['checks', 'boq', boqId],
    queryFn: () => apiGet<{ project_id: string }>(`/v1/boq/boqs/${boqId}`),
    enabled: !!boqId,
    staleTime: 5 * 60_000,
  });
  const projectId = boq.data?.project_id ?? null;
  return useQuery({
    queryKey: ['validation', 'latest', projectId, boqId, null],
    queryFn: async () => {
      const reports = await apiGet<StoredReport[]>(`/v1/validation/reports/?project_id=${projectId}&target_type=boq`);
      return reports.find((r) => r.target_id === boqId) ?? null;
    },
    enabled: !!projectId && !!boqId,
    staleTime: 30_000,
  });
}

export function ChecksPanel() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const boqId = matchPath('/boq/:boqId', pathname)?.params.boqId ?? null;
  const report = useBillReport(boqId);
  const sources = useChecksStore((s) => s.sources);
  const [open, setOpen] = useState(false);

  const findings = useMemo<CheckFinding[]>(() => {
    const fromBill = (report.data?.results ?? []).map((r) => ({
      rule_id: r.rule_id,
      rule_name: r.rule_name ?? r.rule_id,
      severity: toSeverity(r.severity ?? r.status),
      passed: r.passed ?? r.status === 'pass',
      message: r.message,
      element_ref: r.element_ref ?? null,
      suggestion: r.suggestion ?? null,
    }));
    return openFindings([...fromBill, ...Object.values(sources).flat()]);
  }, [report.data, sources]);

  // Rows mount and re-render on their own schedule; keep the marks in step.
  useEffect(() => {
    markFindings(findings);
    if (!findings.length) return;
    const id = window.setInterval(() => markFindings(findings), 1500);
    return () => {
      window.clearInterval(id);
      markFindings([]);
    };
  }, [findings, pathname]);

  const counts = countBySeverity(findings);
  if (!findings.length) return null;

  const reveal = (ref: string | null) => {
    if (!ref) return;
    const el = elementsFor(ref)[0];
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.setAttribute('data-oe-check-flash', '');
    window.setTimeout(() => el.removeAttribute('data-oe-check-flash'), 1600);
  };

  return (
    <>
      <button
        type="button"
        className="oe-checks-toggle"
        data-severity={counts.error ? 'error' : 'warning'}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        data-no-print
      >
        <ListChecks size={14} />
        {t('checks.title', { defaultValue: 'Checks' })}
        <span className="oe-checks-count">{counts.error + counts.warning}</span>
      </button>
      {open && (
        <aside className="oe-checks-sheet" aria-label={t('checks.title', { defaultValue: 'Checks' })} data-no-print>
          <header className="flex items-center justify-between border-b border-border-light px-4 py-3">
            <div>
              <p className="text-sm font-semibold text-content-primary">{t('checks.title', { defaultValue: 'Checks' })}</p>
              <p className="text-xs text-content-secondary">
                {t('checks.summary', {
                  defaultValue: 'Errors: {{errors}}, warnings: {{warnings}}',
                  errors: counts.error,
                  warnings: counts.warning,
                })}
              </p>
            </div>
            <button type="button" onClick={() => setOpen(false)} aria-label={t('common.close', { defaultValue: 'Close' })} className="text-content-tertiary hover:text-content-primary">
              <X size={16} />
            </button>
          </header>
          <ul className="flex-1 divide-y divide-border-light overflow-auto">
            {findings.map((f, i) => (
              <li key={`${f.rule_id}-${f.element_ref ?? i}`}>
                <button
                  type="button"
                  onClick={() => reveal(f.element_ref)}
                  className="flex w-full gap-2 px-4 py-2.5 text-start hover:bg-surface-secondary"
                >
                  <span className="oe-check-dot mt-1.5" data-severity={f.severity} aria-hidden />
                  <span className="min-w-0">
                    <span className="block text-sm text-content-primary">{f.message}</span>
                    {f.suggestion && <span className="mt-0.5 block text-xs text-content-secondary">{f.suggestion}</span>}
                    <span className="mt-0.5 block text-xs text-content-tertiary">{f.rule_name}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {report.data && (
            <footer className="border-t border-border-light px-4 py-2.5">
              <Link to={`/validation?report=${report.data.id}`} className="text-sm font-medium text-oe-blue-text hover:underline">
                {t('checks.open_report', { defaultValue: 'Open the full report' })}
              </Link>
            </footer>
          )}
        </aside>
      )}
    </>
  );
}
