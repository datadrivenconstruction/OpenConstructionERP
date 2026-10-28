// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Validation rules — read-only settings catalogue.
 *
 * Lists every rule set the platform registered at boot
 * (``/api/v1/validation/rule-sets/``) with its rule count, severity
 * spread and the individual rules. Rules themselves are class-based
 * Python objects, so toggling them on/off is a per-project decision
 * the operator drives by passing ``rule_sets=[...]`` when triggering
 * a validation run. We surface that clearly so the page is not a
 * silent stub: it's a real source-of-truth view backed by the
 * registered registry.
 *
 * Why not "save toggle to DB"?
 *   * The shipped registry holds class instances (severity, category,
 *     standard, validate()). Per-tenant enable/disable would require a
 *     per-tenant settings table + extra plumbing to filter at
 *     ``validate()`` time. Out-of-scope for this settings entry; the
 *     run-time ``rule_sets`` argument already gives the operator
 *     per-project control today.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Info,
  ShieldCheck,
} from 'lucide-react';
import clsx from 'clsx';
import {
  Badge,
  Breadcrumb,
  Card,
  EmptyState,
  SkeletonTable,
} from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import {
  listValidationRuleSets,
  type ValidationRuleSetEntry,
} from './api';

const SEVERITY_VARIANT: Record<string, 'error' | 'warning' | 'blue' | 'neutral'> = {
  error: 'error',
  warning: 'warning',
  info: 'blue',
};

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'error') return <AlertOctagon size={12} aria-hidden="true" />;
  if (severity === 'warning') return <AlertTriangle size={12} aria-hidden="true" />;
  return <Info size={12} aria-hidden="true" />;
}

export function ValidationRulesSettingsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [openSet, setOpenSet] = useState<string | null>(null);

  const ruleSetsQ = useQuery({
    queryKey: ['validation', 'rule-sets'],
    queryFn: listValidationRuleSets,
    staleTime: 5 * 60_000,
  });

  const rows = ruleSetsQ.data ?? [];
  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return rows;
    return rows
      .map((rs) => ({
        ...rs,
        rules: rs.rules.filter(
          (r) =>
            r.rule_id.toLowerCase().includes(s) ||
            (r.name || '').toLowerCase().includes(s) ||
            (r.standard || '').toLowerCase().includes(s),
        ),
      }))
      .filter((rs) => rs.name.toLowerCase().includes(s) || rs.rules.length > 0);
  }, [rows, search]);

  return (
    <div className="space-y-4">
      <Breadcrumb
        items={[
          { label: t('nav.group_admin', { defaultValue: 'Admin' }) },
          {
            label: t('validation_rules.title', {
              defaultValue: 'Validation rules',
            }),
          },
        ]}
      />
      <Card className="p-4">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex-1 min-w-[260px]">
            <h1 className="flex items-center gap-2 text-lg font-semibold text-content-primary">
              <ShieldCheck size={18} className="text-oe-blue" />
              {t('validation_rules.title', {
                defaultValue: 'Validation rule catalogue',
              })}
            </h1>
            <div className="mt-1 space-y-1.5 text-xs text-content-tertiary">
              <p>
                {t('validation_rules.intro_1', {
                  defaultValue:
                    'All validation rules built into OpenConstructionERP. Use this catalogue to see what gets checked on every import (BOQs, CAD models, tender data, takeoff results).',
                })}
              </p>
              <p>
                {t('validation_rules.intro_2', {
                  defaultValue:
                    'Browse by severity (errors block, warnings flag, info suggests), by standard (DIN 276 / GAEB / NRM / MasterFormat), or search by name.',
                })}
              </p>
              <p>
                {t('validation_rules.intro_3', {
                  defaultValue:
                    'Per-project rule selection is configured during the import workflow - open a project, go to its Validation tab, and pick which rule sets apply.',
                })}
              </p>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
              <Link
                to="/validation"
                className="inline-flex items-center gap-1 font-medium text-oe-blue hover:underline"
              >
                <ArrowRight size={12} aria-hidden="true" />
                {t('validation_rules.cta_open_runs', {
                  defaultValue: 'Open validation runs',
                })}
              </Link>
              <Link
                to="/modules/developer-guide"
                className="inline-flex items-center gap-1 font-medium text-content-secondary hover:text-oe-blue hover:underline"
              >
                <BookOpen size={12} aria-hidden="true" />
                {t('validation_rules.cta_add_custom', {
                  defaultValue: 'How to add a custom rule',
                })}
              </Link>
            </div>
          </div>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search', { defaultValue: 'Search…' })}
            className="h-9 w-full sm:w-64 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
          />
        </div>
      </Card>
      {ruleSetsQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={5} columns={3} />
        </Card>
      ) : ruleSetsQ.isError ? (
        <Card padding="md">
          <EmptyState
            icon={<AlertOctagon size={22} />}
            title={t('property_dev.validation_rules.load_error', {
              defaultValue: 'Could not load rule registry',
            })}
            description={getErrorMessage(ruleSetsQ.error)}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => ruleSetsQ.refetch(),
            }}
          />
        </Card>
      ) : filtered.length === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<CheckCircle2 size={22} />}
            title={t('property_dev.validation_rules.empty', {
              defaultValue: 'No rule sets registered',
            })}
            description={t('property_dev.validation_rules.empty_desc', {
              defaultValue:
                'The validation engine has not registered any rules. This usually means the validation module is disabled.',
            })}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {filtered.map((rs) => (
            <RuleSetCard
              key={rs.name}
              ruleSet={rs}
              open={openSet === rs.name}
              onToggle={() => setOpenSet(openSet === rs.name ? null : rs.name)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function RuleSetCard({
  ruleSet,
  open,
  onToggle,
}: {
  ruleSet: ValidationRuleSetEntry;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const severityCount = useMemo(() => {
    const out: { error: number; warning: number; info: number } = { error: 0, warning: 0, info: 0 };
    for (const r of ruleSet.rules) {
      if (r.severity === 'error' || r.severity === 'warning' || r.severity === 'info') {
        out[r.severity] += 1;
      }
    }
    return out;
  }, [ruleSet.rules]);

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={`ruleset-${ruleSet.name}-body`}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
      >
        <div className="flex items-center gap-3 min-w-0">
          {open ? (
            <ChevronDown size={14} className="text-content-tertiary flex-shrink-0" />
          ) : (
            <ChevronRight size={14} className="text-content-tertiary flex-shrink-0" />
          )}
          <div className="min-w-0">
            <p className="font-semibold text-content-primary truncate">
              {ruleSet.name}
            </p>
            <p className="text-xs text-content-tertiary truncate">
              {ruleSet.description}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {severityCount.error > 0 && (
            <Badge variant="error" dot>
              {severityCount.error} {t('property_dev.validation_rules.errors', { defaultValue: 'errors' })}
            </Badge>
          )}
          {severityCount.warning > 0 && (
            <Badge variant="warning" dot>
              {severityCount.warning} {t('property_dev.validation_rules.warnings', { defaultValue: 'warnings' })}
            </Badge>
          )}
          {severityCount.info > 0 && (
            <Badge variant="blue" dot>
              {severityCount.info} {t('property_dev.validation_rules.info', { defaultValue: 'info' })}
            </Badge>
          )}
          <Badge variant="neutral">
            {ruleSet.rule_count} {t('property_dev.validation_rules.rules', { defaultValue: 'rules' })}
          </Badge>
        </div>
      </button>
      {open && (
        <div
          id={`ruleset-${ruleSet.name}-body`}
          className="border-t border-border-light"
        >
          {ruleSet.rules.length === 0 ? (
            <p className="px-4 py-3 text-sm text-content-tertiary">
              {t('property_dev.validation_rules.no_rules_in_set', {
                defaultValue: 'No rules in this set.',
              })}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-xs uppercase text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.rule_id', { defaultValue: 'Rule ID' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.name', { defaultValue: 'Name' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.standard', { defaultValue: 'Standard' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.severity', { defaultValue: 'Severity' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.category', { defaultValue: 'Category' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('property_dev.validation_rules.state', { defaultValue: 'State' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {ruleSet.rules.map((r) => (
                  <tr key={r.rule_id} className="border-t border-border-light">
                    <td className="px-3 py-2 font-mono text-xs text-content-secondary">
                      {r.rule_id}
                    </td>
                    <td className="px-3 py-2 text-content-primary">{r.name}</td>
                    <td className="px-3 py-2 text-xs">
                      <Badge variant="neutral">{r.standard}</Badge>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <span
                        className={clsx(
                          'inline-flex items-center gap-1',
                          r.severity === 'error'
                            ? 'text-rose-700'
                            : r.severity === 'warning'
                              ? 'text-amber-700'
                              : 'text-sky-700',
                        )}
                      >
                        <SeverityIcon severity={r.severity} />
                        <Badge variant={SEVERITY_VARIANT[r.severity] ?? 'neutral'}>
                          {r.severity}
                        </Badge>
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-content-secondary">
                      {r.category}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.enabled ? (
                        <Badge variant="success" dot>
                          {t('property_dev.validation_rules.enabled', { defaultValue: 'enabled' })}
                        </Badge>
                      ) : (
                        <Badge variant="neutral" dot>
                          {t('property_dev.validation_rules.disabled', { defaultValue: 'disabled' })}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  );
}
