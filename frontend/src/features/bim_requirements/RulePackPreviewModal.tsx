// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * RulePackPreviewModal — preview + install dialog for a YAML rule pack.
 *
 * Two modes:
 *   - Seed mode (when `seedPack` is supplied): the YAML loads from the
 *     seed pack and the editor is read-only until the user toggles
 *     "Edit YAML" on.
 *   - Custom mode (`seedPack` is null): the editor starts empty so the
 *     user can paste their own YAML.
 *
 * The component debounces (800 ms) every change to `yaml_text` and
 * calls the `preview-yaml` endpoint. If the user picks a BIM model the
 * preview request also returns a dry-run report (pass/fail counts per
 * rule).
 *
 * "Install to project" → ConfirmDialog → POST `install-from-yaml`,
 * toast, close, invalidate `requirement-sets`.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Pencil,
  XCircle,
  Eye,
  Info,
} from 'lucide-react';
import clsx from 'clsx';

import { ConfirmDialog, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet } from '@/shared/lib/api';
import { installYaml, previewYaml } from './api';
import type {
  PreviewYamlResponse,
  ParsedRule,
  RuleSeverity,
  DryRunElementResult,
} from './types';
import { YamlEditor } from './YamlEditor';
import type { SeedPack } from './SEED_PACKS';

const PREVIEW_DEBOUNCE_MS = 800;

export interface RulePackPreviewModalProps {
  open: boolean;
  onClose: () => void;
  /** When given, the modal opens in seed mode with the YAML preloaded. */
  seedPack: SeedPack | null;
  /** Required to install (POST install-from-yaml). */
  projectId: string | null;
  /** data-testid override. */
  testId?: string;
}

interface BIMModelSummary {
  id: string;
  name: string;
}

interface BIMModelsResponse {
  items?: BIMModelSummary[];
}

const SEVERITY_CHIP: Record<RuleSeverity, string> = {
  error: 'bg-red-50 text-red-700 border-red-200',
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  info: 'bg-blue-50 text-blue-700 border-blue-200',
};

function severityLabelKey(s: RuleSeverity): string {
  switch (s) {
    case 'error':
      return 'rulePacks.severity_error';
    case 'warning':
      return 'rulePacks.severity_warning';
    case 'info':
      return 'rulePacks.severity_info';
  }
}

/** Renders the actual failing elements for one rule in the drilldown.
 *  The backend dry-run already returns one row per failing (rule, element)
 *  pair with `element_id` + an optional `message`, so we list them here
 *  instead of promising a non-existent click-through. Caps the rendered
 *  list at 50 rows to keep the panel light. */
function FailingElementsList({
  rows,
  total,
}: {
  rows: DryRunElementResult[];
  total: number;
}) {
  const { t } = useTranslation();
  const MAX = 50;
  const shown = rows.slice(0, MAX);
  return (
    <div data-testid="failing-elements-list">
      <p className="mb-1.5 font-medium text-content-secondary">
        {t('bim_requirements.failing_elements_heading', {
          defaultValue: '{{count}} element(s) failed this rule:',
          count: total,
        })}
      </p>
      <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded border border-border-light bg-surface-primary p-1.5">
        {shown.map((r, i) => (
          <li
            key={`${r.element_id}-${i}`}
            className="flex items-baseline gap-2 px-1 py-0.5"
            data-testid="failing-element-row"
          >
            <code className="shrink-0 font-mono text-[10px] text-content-primary">
              {r.element_id}
            </code>
            {r.message && (
              <span className="truncate text-[10px] text-content-tertiary">{r.message}</span>
            )}
          </li>
        ))}
      </ul>
      {total > shown.length && (
        <p className="mt-1 text-[10px] text-content-tertiary">
          {t('bim_requirements.failing_elements_truncated', {
            defaultValue: 'Showing first {{shown}} of {{total}} failing elements.',
            shown: shown.length,
            total,
          })}
        </p>
      )}
    </div>
  );
}

export function RulePackPreviewModal({
  open,
  onClose,
  seedPack,
  projectId,
  testId = 'rule-pack-preview-modal',
}: RulePackPreviewModalProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const isSeedMode = seedPack !== null;

  const [yamlText, setYamlText] = useState<string>('');
  const [readonly, setReadonly] = useState<boolean>(false);
  const [modelId, setModelId] = useState<string>('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewYamlResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastRequestIdRef = useRef(0);

  // Reset state whenever the modal re-opens with a new mode.
  useEffect(() => {
    if (!open) return;
    if (seedPack) {
      setYamlText(seedPack.yaml);
      setReadonly(true);
    } else {
      setYamlText('');
      setReadonly(false);
    }
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(false);
    setModelId('');
    setConfirmOpen(false);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
  }, [open, seedPack]);

  // Models query — used for the optional dry-run model picker. Only
  // fires when the modal is open AND a project is known; otherwise the
  // dropdown stays empty + the preview is a pure parse.
  const modelsQuery = useQuery<BIMModelsResponse>({
    queryKey: ['rule-pack-preview-models', projectId],
    queryFn: () =>
      projectId
        ? apiGet<BIMModelsResponse>(
            `/v1/bim_hub/?project_id=${encodeURIComponent(projectId)}`,
          )
        : Promise.resolve({ items: [] }),
    enabled: !!projectId && open,
    staleTime: 60_000,
  });
  const models = modelsQuery.data?.items ?? [];

  // Debounced preview — fires whenever the YAML or model selection
  // changes. Empty YAML short-circuits to a cleared preview state.
  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!yamlText.trim()) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    const reqId = ++lastRequestIdRef.current;
    debounceRef.current = setTimeout(() => {
      previewYaml({ yaml_text: yamlText, model_id: modelId || undefined })
        .then((res) => {
          if (reqId !== lastRequestIdRef.current) return;
          setPreview(res);
          setPreviewError(null);
        })
        .catch((err: unknown) => {
          if (reqId !== lastRequestIdRef.current) return;
          setPreview(null);
          setPreviewError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (reqId !== lastRequestIdRef.current) return;
          setPreviewLoading(false);
        });
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [open, yamlText, modelId]);

  const installMutation = useMutation({
    mutationKey: ['install-yaml-rule-pack'],
    mutationFn: () => {
      if (!projectId) {
        return Promise.reject(new Error('No active project'));
      }
      return installYaml({ yaml_text: yamlText, project_id: projectId });
    },
    onSuccess: async (res) => {
      await queryClient.invalidateQueries({ queryKey: ['requirement-sets'] });
      addToast({
        type: 'success',
        title: t('rulePacks.install_success', { defaultValue: 'Rule pack installed' }),
        message: t('rulePacks.installed_count', {
          defaultValue: '{{count}} rules added to this project.',
          count: res.rules_installed,
        }),
      });
      setConfirmOpen(false);
      onClose();
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('rulePacks.preview_error', { defaultValue: 'Install failed' }),
        message: err instanceof Error ? err.message : String(err),
      });
      setConfirmOpen(false);
    },
  });

  const rules: ParsedRule[] = useMemo(
    () => (preview?.pack?.rules ?? []) as ParsedRule[],
    [preview],
  );

  // The backend dry-run report is a FLAT list of per-(rule, element) rows
  // ({ rule_id, element_id, passed, ... }). Aggregate them here into a
  // per-rule { pass, fail } tally — one row per element, so each rule_id
  // appears once per evaluated element.
  const dryRunByRule = useMemo(() => {
    const map = new Map<string, { pass: number; fail: number }>();
    for (const r of preview?.dry_run?.results ?? []) {
      const acc = map.get(r.rule_id) ?? { pass: 0, fail: 0 };
      if (r.passed) acc.pass += 1;
      else acc.fail += 1;
      map.set(r.rule_id, acc);
    }
    return map;
  }, [preview]);

  // The failing element rows per rule, so the drilldown can actually list
  // *which* elements failed (the backend already returns element_id +
  // message + evidence on each row). Keyed by rule_id.
  const failingElementsByRule = useMemo(() => {
    const map = new Map<string, DryRunElementResult[]>();
    for (const r of preview?.dry_run?.results ?? []) {
      if (r.passed) continue;
      const list = map.get(r.rule_id) ?? [];
      list.push(r);
      map.set(r.rule_id, list);
    }
    return map;
  }, [preview]);

  // Test-against-current-model state — only meaningful when a model is
  // selected AND the preview returned a dry_run report. Computes a
  // per-rule status (pass / warn / fail) by combining the rule's severity
  // with its fail count: a `warning` rule with fails stays "warn" (amber)
  // while an `error` rule with fails escalates to "fail" (red).
  const ruleStatuses = useMemo(() => {
    type RuleStatus = 'pass' | 'warn' | 'fail';
    const out: Array<{
      rule: ParsedRule;
      status: RuleStatus;
      pass: number;
      fail: number;
    }> = [];
    for (const rule of rules) {
      const dr = dryRunByRule.get(rule.id);
      if (!dr) {
        out.push({ rule, status: 'pass', pass: 0, fail: 0 });
        continue;
      }
      const fail = dr.fail;
      let status: RuleStatus = 'pass';
      if (fail > 0) {
        status = rule.severity === 'error' ? 'fail' : 'warn';
      }
      out.push({ rule, status, pass: dr.pass, fail });
    }
    return out;
  }, [rules, dryRunByRule]);

  const ruleStatusCounts = useMemo(() => {
    const counts = { pass: 0, warn: 0, fail: 0 };
    for (const r of ruleStatuses) counts[r.status]++;
    return counts;
  }, [ruleStatuses]);

  const hasDryRun = !!modelId && !!preview?.dry_run;
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);

  // Clear the per-rule drilldown whenever the dataset shifts.
  useEffect(() => {
    setSelectedRuleId(null);
  }, [preview, modelId]);

  const previewSucceeded = !!preview && !previewError && rules.length > 0;
  const canInstall = previewSucceeded && !!projectId && !installMutation.isPending;

  const handleYamlChange = useCallback((next: string) => {
    setYamlText(next);
  }, []);

  const handleToggleReadonly = useCallback(() => {
    setReadonly((r) => !r);
  }, []);

  const handleRequestInstall = useCallback(() => {
    if (!canInstall) return;
    setConfirmOpen(true);
  }, [canInstall]);

  const handleConfirmInstall = useCallback(() => {
    installMutation.mutate();
  }, [installMutation]);

  const title = isSeedMode
    ? seedPack!.name
    : t('rulePacks.paste_custom', { defaultValue: 'Paste your own YAML' });

  const footer = (
    <>
      <button
        type="button"
        onClick={onClose}
        data-testid={`${testId}-cancel`}
        className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-[12px] font-medium text-content-secondary hover:bg-surface-secondary"
      >
        {t('rulePacks.cancel', { defaultValue: 'Cancel' })}
      </button>
      <button
        type="button"
        onClick={handleRequestInstall}
        disabled={!canInstall}
        data-testid={`${testId}-install`}
        className={clsx(
          'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-semibold shadow-sm',
          canInstall
            ? 'bg-oe-blue text-white hover:bg-oe-blue-dark'
            : 'cursor-not-allowed bg-surface-secondary text-content-tertiary',
        )}
      >
        {installMutation.isPending ? (
          <>
            <Loader2 size={12} className="animate-spin" />
            {t('rulePacks.installing', { defaultValue: 'Installing…' })}
          </>
        ) : (
          t('rulePacks.install', { defaultValue: 'Install to project' })
        )}
      </button>
    </>
  );

  return (
    <>
      <WideModal
        open={open}
        onClose={onClose}
        title={title}
        size="lg"
        footer={footer}
        busy={installMutation.isPending}
      >
        <div className="flex flex-col gap-4" data-testid={testId}>
          {/* Plain-language reminder of what installing does at import time. */}
          <p
            className="flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-[11px] leading-relaxed text-content-secondary"
            data-testid={`${testId}-explainer`}
          >
            <Info size={13} className="mt-0.5 flex-shrink-0 text-oe-blue" />
            <span>
              {t('rulePacks.modal_explainer', {
                defaultValue:
                  'These rules describe the data a delivered model must carry. Installing adds them to this project, where they run automatically each time a model is imported and flag any element that is missing or fails a requirement. Preview them below, and dry-run against a loaded model before you install.',
              })}
            </span>
          </p>

          {/* Toolbar — readonly toggle (seed mode only) + model picker */}
          <div className="flex flex-wrap items-center gap-3">
            {isSeedMode && (
              <button
                type="button"
                onClick={handleToggleReadonly}
                data-testid={`${testId}-readonly-toggle`}
                aria-pressed={!readonly}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium',
                  readonly
                    ? 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary'
                    : 'border-oe-blue/40 bg-oe-blue/10 text-oe-blue',
                )}
              >
                {readonly ? <Pencil size={12} /> : <Eye size={12} />}
                {readonly
                  ? t('rulePacks.edit_yaml', { defaultValue: 'Edit YAML' })
                  : t('rulePacks.readonly_toggle', { defaultValue: 'View only' })}
              </button>
            )}
            <div className="ml-auto flex items-center gap-2">
              <label
                htmlFor={`${testId}-model`}
                className="text-[11px] font-medium text-content-secondary"
              >
                {t('rulePacks.select_model', { defaultValue: 'Dry-run against model' })}
              </label>
              <select
                id={`${testId}-model`}
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                disabled={models.length === 0}
                data-testid={`${testId}-model-select`}
                className="rounded-lg border border-border-light bg-surface-primary px-2 py-1 text-[11px] text-content-primary focus:border-oe-blue focus:outline-none disabled:opacity-50"
              >
                <option value="">
                  {t('rulePacks.dry_run', { defaultValue: '- no dry run -' })}
                </option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* YAML editor */}
          <YamlEditor
            value={yamlText}
            onChange={handleYamlChange}
            readonly={readonly}
            error={previewError}
            parsed={previewSucceeded}
            rows={16}
            placeholder={
              isSeedMode
                ? undefined
                : t('rulePacks.paste_custom', { defaultValue: 'Paste your own YAML' })
            }
            testId={`${testId}-yaml`}
          />

          {/* Live preview status */}
          <div className="flex items-center justify-between text-[11px]">
            <span
              className="text-content-tertiary"
              data-testid={`${testId}-preview-status`}
            >
              {previewLoading ? (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 size={12} className="animate-spin" />
                  {t('rulePacks.preview', { defaultValue: 'Preview & install' })}…
                </span>
              ) : previewSucceeded ? (
                <span className="inline-flex items-center gap-1.5 text-emerald-700">
                  <CheckCircle2 size={12} />
                  {t('rulePacks.rules_count', {
                    defaultValue: '{{count}} rules',
                    count: rules.length,
                  })}
                </span>
              ) : previewError ? (
                <span className="inline-flex items-center gap-1.5 text-red-700">
                  <XCircle size={12} />
                  {t('rulePacks.preview_error', { defaultValue: 'Preview failed' })}
                </span>
              ) : (
                ''
              )}
            </span>
          </div>

          {/* Parsed rules list */}
          {rules.length > 0 && (
            <ul
              data-testid={`${testId}-rules-list`}
              className="divide-y divide-border-light overflow-hidden rounded-lg border border-border-light bg-surface-primary"
            >
              {rules.map((rule) => {
                const dr = dryRunByRule.get(rule.id);
                return (
                  <li
                    key={rule.id}
                    className="flex items-start justify-between gap-3 px-3 py-2"
                    data-testid={`${testId}-rule-${rule.id}`}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-[12px] font-medium text-content-primary">
                        {rule.name}
                      </p>
                      {rule.rationale && (
                        <p className="mt-0.5 line-clamp-2 text-[11px] text-content-tertiary">
                          {rule.rationale}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-1.5">
                      {dr && (
                        <span
                          className="rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
                          data-testid={`${testId}-rule-${rule.id}-dryrun`}
                        >
                          {dr.pass} / {dr.pass + dr.fail}
                        </span>
                      )}
                      <span
                        className={clsx(
                          'rounded-full border px-1.5 py-0.5 text-[10px] font-medium',
                          SEVERITY_CHIP[rule.severity],
                        )}
                        data-testid={`${testId}-rule-${rule.id}-severity`}
                      >
                        {t(severityLabelKey(rule.severity), { defaultValue: rule.severity })}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          {/* Test against current model — only when a dry-run is available. */}
          {hasDryRun && rules.length > 0 && (
            <section
              data-testid={`${testId}-test-mode`}
              className="rounded-lg border border-border-light bg-surface-primary p-3"
            >
              <header className="mb-2 flex items-center justify-between">
                <h3 className="text-[12px] font-semibold text-content-primary">
                  {t('rulePacks.test_mode_title', {
                    defaultValue: 'Test against current model',
                  })}
                </h3>
                <div
                  className="flex items-center gap-1.5"
                  data-testid={`${testId}-test-mode-summary`}
                >
                  <span
                    className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700"
                    data-testid={`${testId}-test-mode-pass-count`}
                    data-count={ruleStatusCounts.pass}
                  >
                    {ruleStatusCounts.pass}{' '}
                    {t('rulePacks.test_mode_pass_label', { defaultValue: 'pass' })}
                  </span>
                  <span
                    className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700"
                    data-testid={`${testId}-test-mode-warn-count`}
                    data-count={ruleStatusCounts.warn}
                  >
                    {ruleStatusCounts.warn}{' '}
                    {t('rulePacks.test_mode_warn_label', { defaultValue: 'warn' })}
                  </span>
                  <span
                    className="rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700"
                    data-testid={`${testId}-test-mode-fail-count`}
                    data-count={ruleStatusCounts.fail}
                  >
                    {ruleStatusCounts.fail}{' '}
                    {t('rulePacks.test_mode_fail_label_summary', { defaultValue: 'fail' })}
                  </span>
                </div>
              </header>

              <ul
                data-testid={`${testId}-test-mode-rules`}
                className="divide-y divide-border-light overflow-hidden rounded-md border border-border-light"
              >
                {ruleStatuses.map(({ rule, status, fail }) => {
                  const statusChip =
                    status === 'pass'
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      : status === 'warn'
                        ? 'bg-amber-50 text-amber-700 border-amber-200'
                        : 'bg-red-50 text-red-700 border-red-200';
                  const StatusIcon =
                    status === 'pass'
                      ? CheckCircle2
                      : status === 'warn'
                        ? AlertTriangle
                        : XCircle;
                  const isExpanded = selectedRuleId === rule.id;
                  return (
                    <li
                      key={rule.id}
                      data-testid={`${testId}-test-mode-rule-${rule.id}`}
                      data-status={status}
                    >
                      <button
                        type="button"
                        onClick={() =>
                          setSelectedRuleId((prev) => (prev === rule.id ? null : rule.id))
                        }
                        aria-expanded={isExpanded}
                        data-testid={`${testId}-test-mode-rule-${rule.id}-toggle`}
                        className="flex w-full items-center justify-between gap-3 bg-surface-primary px-3 py-2 text-left hover:bg-surface-secondary"
                      >
                        <span className="flex min-w-0 flex-1 items-center gap-2">
                          <span
                            className={clsx(
                              'inline-flex h-5 items-center gap-1 rounded-full border px-1.5 text-[10px] font-medium',
                              statusChip,
                            )}
                            data-testid={`${testId}-test-mode-rule-${rule.id}-status`}
                          >
                            <StatusIcon size={10} />
                            {t(`rulePacks.test_mode_status_${status}`, {
                              defaultValue: status,
                            })}
                          </span>
                          <span className="truncate text-[12px] font-medium text-content-primary">
                            {rule.name}
                          </span>
                        </span>
                        <span className="flex flex-shrink-0 items-center gap-1.5">
                          <span
                            className="rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary"
                            data-testid={`${testId}-test-mode-rule-${rule.id}-fail-count`}
                            data-count={fail}
                          >
                            {fail}{' '}
                            {t('rulePacks.test_mode_fail_label', { defaultValue: 'fail' })}
                          </span>
                          <ChevronRight
                            size={12}
                            className={clsx(
                              'text-content-tertiary transition-transform',
                              isExpanded && 'rotate-90',
                            )}
                          />
                        </span>
                      </button>
                      {isExpanded && (
                        <div
                          data-testid={`${testId}-test-mode-rule-${rule.id}-elements`}
                          data-fail-count={fail}
                          className="border-t border-border-light bg-surface-secondary px-3 py-2 text-[11px] text-content-secondary"
                        >
                          {fail === 0 ? (
                            <p>
                              {t('rulePacks.test_mode_no_failures', {
                                defaultValue: 'No failing elements for this rule.',
                              })}
                            </p>
                          ) : (
                            <FailingElementsList
                              rows={failingElementsByRule.get(rule.id) ?? []}
                              total={fail}
                            />
                          )}
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      </WideModal>

      <ConfirmDialog
        open={confirmOpen}
        onConfirm={handleConfirmInstall}
        onCancel={() => setConfirmOpen(false)}
        title={t('rulePacks.confirm_install_title', { defaultValue: 'Install rule pack?' })}
        message={t('rulePacks.confirm_install_body', {
          defaultValue:
            'This adds {{count}} rules to the active project. You can deactivate them later.',
          count: rules.length,
        })}
        confirmLabel={t('rulePacks.install', { defaultValue: 'Install to project' })}
        cancelLabel={t('rulePacks.cancel', { defaultValue: 'Cancel' })}
        variant="warning"
        loading={installMutation.isPending}
      />
    </>
  );
}

export default RulePackPreviewModal;
