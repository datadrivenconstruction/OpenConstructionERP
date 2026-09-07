// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Compliance dashboard + regulator-report launcher (task #139).
 *
 * Backed by:
 *   GET  /api/v1/property-dev/compliance/dashboard?dev_id=...
 *   POST /api/v1/property-dev/compliance/run-checks?dev_id=...
 *   GET  /api/v1/property-dev/compliance/regulator-reports?dev_id=...&regulator=...&quarter=...
 *
 * All user-facing copy is routed through `useTranslation()` — propdev.compliance.*
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileDown,
  Info,
  Loader2,
  Play,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { compareNames } from '@/shared/lib/collator';
import {
  ComplianceDashboard,
  ComplianceRuleResult,
  RegulatorCode,
  fetchComplianceDashboard,
  fetchRegulatorReport,
  runComplianceChecks,
} from './api';

const REGULATORS: { code: RegulatorCode; labelKey: string }[] = [
  { code: 'RERA', labelKey: 'propdev.compliance.regulator.rera' },
  { code: 'MAHARERA', labelKey: 'propdev.compliance.regulator.maharera' },
  { code: '214FZ', labelKey: 'propdev.compliance.regulator.fz214' },
  { code: 'CMA', labelKey: 'propdev.compliance.regulator.cma' },
];

function currentQuarter(now: Date = new Date()): string {
  const q = Math.floor(now.getUTCMonth() / 3) + 1;
  return `${now.getUTCFullYear()}-Q${q}`;
}

function downloadBase64(b64: string, filename: string, mime: string): void {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function badgeVariantFor(
  passed: boolean,
  severity: ComplianceRuleResult['severity'],
): 'success' | 'warning' | 'error' | 'neutral' {
  if (passed) return 'success';
  if (severity === 'error') return 'error';
  if (severity === 'warning') return 'warning';
  return 'neutral';
}

interface CompliancePageProps {
  devId: string;
  developmentLabel?: string;
}

export function CompliancePage({
  devId,
  developmentLabel,
}: CompliancePageProps): JSX.Element {
  const { t, i18n } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [quarter, setQuarter] = useState<string>(currentQuarter());
  const [busyRegulator, setBusyRegulator] = useState<RegulatorCode | null>(null);

  const dashboardQuery = useQuery<ComplianceDashboard>({
    queryKey: ['property-dev', 'compliance', 'dashboard', devId, i18n.language],
    queryFn: () => fetchComplianceDashboard(devId, i18n.language),
    enabled: Boolean(devId),
  });

  const runChecksMutation = useMutation({
    mutationFn: () => runComplianceChecks(devId, i18n.language),
    onSuccess: (data) => {
      qc.setQueryData(
        ['property-dev', 'compliance', 'dashboard', devId, i18n.language],
        data,
      );
      addToast({
        type: 'success',
        title: t('propdev.compliance.run_success'),
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  const downloadReport = async (regulator: RegulatorCode): Promise<void> => {
    setBusyRegulator(regulator);
    try {
      const report = await fetchRegulatorReport(devId, regulator, quarter);
      downloadBase64(
        report.pdf_base64,
        `${regulator}_${quarter}.pdf`,
        'application/pdf',
      );
      const payloadMime =
        report.payload_format === 'xml' ? 'application/xml' : 'application/json';
      const payloadExt = report.payload_format === 'xml' ? 'xml' : 'json';
      downloadBase64(
        report.payload_base64,
        `${regulator}_${quarter}.${payloadExt}`,
        payloadMime,
      );
      addToast({
        type: 'success',
        title: t('propdev.compliance.regulator_downloaded', { regulator }),
      });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusyRegulator(null);
    }
  };

  const counts = dashboardQuery.data?.counts ?? {};
  const groupedByRule = useMemo(() => {
    const groups = new Map<string, ComplianceRuleResult[]>();
    for (const r of dashboardQuery.data?.results ?? []) {
      if (!groups.has(r.rule_id)) groups.set(r.rule_id, []);
      groups.get(r.rule_id)!.push(r);
    }
    return Array.from(groups.entries())
      .map(([ruleId, results]) => ({
        ruleId,
        ruleName: results[0]?.rule_name ?? ruleId,
        severity: results[0]?.severity ?? ('info' as ComplianceRuleResult['severity']),
        category: results[0]?.category ?? 'compliance',
        passed: results.every((r) => r.passed),
        results,
      }))
      .sort((a, b) => {
        if (a.passed === b.passed) return compareNames(a.ruleName, b.ruleName);
        return a.passed ? 1 : -1;
      });
  }, [dashboardQuery.data]);

  const toggle = (ruleId: string): void => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(ruleId)) next.delete(ruleId);
      else next.add(ruleId);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            {t('propdev.compliance.title')}
          </h1>
          {developmentLabel ? (
            <p className="text-sm text-zinc-500">{developmentLabel}</p>
          ) : null}
        </div>
        <Button
          variant="primary"
          onClick={() => runChecksMutation.mutate()}
          disabled={runChecksMutation.isPending}
          icon={
            runChecksMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )
          }
        >
          {t('propdev.compliance.run_checks')}
        </Button>
      </header>

      {/* Traffic-light tiles */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
        <Card padding="sm" className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">
              {t('propdev.compliance.tile.passed')}
            </p>
            <p className="text-2xl font-semibold text-emerald-600">
              {counts.passed ?? 0}
            </p>
          </div>
          <CheckCircle2 className="h-7 w-7 text-emerald-500" />
        </Card>
        <Card padding="sm" className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">
              {t('propdev.compliance.tile.warnings')}
            </p>
            <p className="text-2xl font-semibold text-amber-600">
              {counts.warnings ?? 0}
            </p>
          </div>
          <AlertTriangle className="h-7 w-7 text-amber-500" />
        </Card>
        <Card padding="sm" className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">
              {t('propdev.compliance.tile.errors')}
            </p>
            <p className="text-2xl font-semibold text-rose-600">
              {counts.errors ?? 0}
            </p>
          </div>
          <AlertOctagon className="h-7 w-7 text-rose-500" />
        </Card>
        <Card padding="sm" className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-zinc-500">
              {t('propdev.compliance.tile.infos')}
            </p>
            <p className="text-2xl font-semibold text-sky-600">
              {counts.infos ?? 0}
            </p>
          </div>
          <Info className="h-7 w-7 text-sky-500" />
        </Card>
      </div>

      {/* Rule list */}
      <Card padding="none" className="overflow-hidden">
        <div className="border-b border-zinc-200 p-4 dark:border-zinc-800">
          <h2 className="font-medium">
            {t('propdev.compliance.results_title')}
          </h2>
        </div>
        {dashboardQuery.isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={5} columns={3} />
          </div>
        ) : dashboardQuery.isError ? (
          <div className="p-4">
            <EmptyState
              icon={<AlertOctagon size={22} />}
              title={t('propdev.compliance.load_error_title', {
                defaultValue: 'Could not load compliance results',
              })}
              description={getErrorMessage(dashboardQuery.error)}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => dashboardQuery.refetch(),
              }}
            />
          </div>
        ) : groupedByRule.length === 0 ? (
          <div className="p-4">
            <EmptyState
              icon={<CheckCircle2 size={22} />}
              title={t('propdev.compliance.no_rules_title', {
                defaultValue: 'No compliance checks run yet',
              })}
              description={t('propdev.compliance.no_rules_desc', {
                defaultValue:
                  'Click "Run checks" above to evaluate this development against the configured rule sets.',
              })}
            />
          </div>
        ) : (
          <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {groupedByRule.map((rule) => {
              const isOpen = expanded.has(rule.ruleId);
              const failing = rule.results.filter((r) => !r.passed);
              const badgeKind: 'success' | 'warning' | 'error' | 'neutral' =
                badgeVariantFor(rule.passed, rule.severity);
              const badgeKey = rule.passed
                ? 'propdev.compliance.badge.pass'
                : `propdev.compliance.badge.${rule.severity}`;
              return (
                <li key={rule.ruleId}>
                  <button
                    type="button"
                    onClick={() => toggle(rule.ruleId)}
                    className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-zinc-900"
                  >
                    <div className="flex items-center gap-3">
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4 text-zinc-400" />
                      ) : (
                        <ChevronRight className="h-4 w-4 text-zinc-400" />
                      )}
                      <span
                        className={clsx(
                          'inline-flex h-2.5 w-2.5 rounded-full',
                          rule.passed && 'bg-emerald-500',
                          !rule.passed && rule.severity === 'error' && 'bg-rose-500',
                          !rule.passed && rule.severity === 'warning' && 'bg-amber-500',
                          !rule.passed && rule.severity === 'info' && 'bg-sky-500',
                        )}
                        aria-hidden="true"
                      />
                      <div>
                        <p className="text-sm font-medium">{rule.ruleName}</p>
                        <p className="text-xs text-zinc-500">
                          {rule.category} · {rule.ruleId}
                        </p>
                      </div>
                    </div>
                    <Badge variant={badgeKind}>{t(badgeKey)}</Badge>
                  </button>
                  {isOpen && failing.length > 0 ? (
                    <ul className="space-y-1 bg-zinc-50 px-12 py-3 text-xs dark:bg-zinc-900">
                      {failing.map((r, idx) => (
                        <li
                          key={`${rule.ruleId}-${idx}`}
                          className="flex gap-3"
                        >
                          <span className="flex-1">
                            <span className="block">{r.message}</span>
                            {r.suggestion ? (
                              <span className="mt-0.5 block text-zinc-500">
                                {r.suggestion}
                              </span>
                            ) : null}
                          </span>
                          {r.element_ref ? (
                            <code className="rounded bg-zinc-200 px-1.5 py-0.5 text-[10px] dark:bg-zinc-800">
                              {r.element_ref}
                            </code>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* Regulator-report cards */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">
            {t('propdev.compliance.regulator_reports_title')}
          </h2>
          <div className="flex items-center gap-2 text-sm">
            <label
              htmlFor="propdev-compliance-quarter"
              className="text-zinc-500"
            >
              {t('propdev.compliance.quarter')}
            </label>
            <input
              id="propdev-compliance-quarter"
              type="text"
              value={quarter}
              onChange={(e) => setQuarter(e.target.value.trim().toUpperCase())}
              placeholder="2026-Q2"
              pattern="\d{4}-Q[1-4]"
              className="w-28 rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          {REGULATORS.map(({ code, labelKey }) => {
            const isBusy = busyRegulator === code;
            return (
              <Card key={code} padding="sm" className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{t(labelKey)}</h3>
                  <Badge variant="neutral">{code}</Badge>
                </div>
                <p className="text-xs text-zinc-500">
                  {t(`propdev.compliance.regulator_desc.${code.toLowerCase()}`)}
                </p>
                <Button
                  variant="secondary"
                  onClick={() => downloadReport(code)}
                  disabled={
                    busyRegulator !== null ||
                    !/^\d{4}-Q[1-4]$/.test(quarter)
                  }
                  icon={
                    isBusy ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <FileDown className="h-4 w-4" />
                    )
                  }
                >
                  {t('propdev.compliance.generate_report')}
                </Button>
              </Card>
            );
          })}
        </div>
      </section>
    </div>
  );
}

/**
 * Route wrapper for `/property-dev/developments/:devId/compliance`.
 *
 * The panel above keeps its prop API because it is meant to be embeddable and
 * a router cannot pass props. The dev-scoped screens next door
 * (`PricingEnginePage`, `InventoryMapPage`) read `useParams` inside the
 * exported component itself; this wrapper gives the route the same shape
 * without collapsing the panel into it.
 *
 * `developmentLabel` is deliberately not passed. It only draws a subtitle, and
 * fetching a development just to name one would put a second request in front
 * of the dashboard. A missing `devId` leaves the panel's queries disabled
 * rather than firing a request for nothing.
 */
export function CompliancePageRoute(): JSX.Element {
  const { devId = '' } = useParams<{ devId: string }>();
  return <CompliancePage devId={devId} />;
}

export default CompliancePage;
