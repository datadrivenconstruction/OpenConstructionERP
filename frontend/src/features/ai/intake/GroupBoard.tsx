// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (editable group board).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Checkpoint B: the editable estimate groups grouped by foreman stage, each
// with a real probe coverage badge, the computed quantity + unit, an
// estimated flag, and include / remove controls. The user can add curated or
// custom work. Nothing is matched until "Confirm group board" is pressed
// (human-confirmed AI: explicit confirmation before any rate is fetched).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge, Button } from '@/shared/ui';
import { Plus, Trash2, Check, Layers } from 'lucide-react';
import clsx from 'clsx';
import {
  coverageLabel,
  coverageTally,
  coverageVariant,
  groupPackagesByStage,
  scorePercent,
} from './helpers';
import { DependencyWarnings } from './DependencyWarnings';
import type { ComposedPackage, IntakePackagesRequest, IntakeState } from './types';
import { formatNumber } from '@/shared/lib/formatters';

interface GroupBoardProps {
  state: IntakeState;
  /** Edit the board (add / remove / toggle). Re-probes on the server. */
  onEditPackages: (body: IntakePackagesRequest) => void;
  /** Confirm the board (checkpoint B) -> bridges to the match pipeline. */
  onFinish: () => void;
  busy?: boolean;
  finishing?: boolean;
}

const STAGE_LABELS: Record<string, { key: string; fb: string }> = {
  demo: { key: 'aiest.stage.demo', fb: 'Demolition' },
  structure: { key: 'aiest.stage.structure', fb: 'Structure' },
  rough: { key: 'aiest.stage.rough', fb: 'First fix' },
  close: { key: 'aiest.stage.close', fb: 'Close up' },
  finish: { key: 'aiest.stage.finish', fb: 'Finishes' },
  commission: { key: 'aiest.stage.commission', fb: 'Commission' },
};

export function GroupBoard({
  state,
  onEditPackages,
  onFinish,
  busy,
  finishing,
}: GroupBoardProps) {
  const { t } = useTranslation();
  const [customText, setCustomText] = useState('');

  const stageGroups = groupPackagesByStage(state.packages);
  const tally = coverageTally(state.packages);

  const addCustom = () => {
    const text = customText.trim();
    if (!text) return;
    onEditPackages({ add: [{ custom_description: text }] });
    setCustomText('');
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Layers size={15} className="text-oe-blue" />
        {t('aiest.board.title', { defaultValue: 'Work packages' })}
      </div>

      <DependencyWarnings warnings={state.dependency_warnings} />

      {stageGroups.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-content-tertiary">
          {t('aiest.board.empty', {
            defaultValue: 'No work packages yet. Add custom work below or revisit the parameters.',
          })}
        </p>
      ) : (
        <div className="space-y-4">
          {stageGroups.map((sg) => {
            const stageLabel = STAGE_LABELS[sg.stage] ?? { key: '', fb: sg.stage };
            return (
              <section key={sg.stage}>
                <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                  {t(stageLabel.key, { defaultValue: stageLabel.fb })}
                </h4>
                <ul className="space-y-1.5">
                  {sg.packages.map((pkg) => (
                    <PackageRow
                      key={pkg.package_key}
                      pkg={pkg}
                      onToggle={(selected) =>
                        onEditPackages({ toggle: { [pkg.package_key]: selected } })
                      }
                      onRemove={() => onEditPackages({ remove: [pkg.package_key] })}
                      disabled={busy}
                    />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}

      {/* Add custom work — composer probes it immediately on the server. */}
      <div className="rounded-xl border border-dashed border-border p-3">
        <label
          htmlFor="aiest-add-custom"
          className="mb-1.5 block text-xs font-medium text-content-secondary"
        >
          {t('aiest.board.add_custom_label', { defaultValue: 'Add custom work' })}
        </label>
        <div className="flex gap-2">
          <input
            id="aiest-add-custom"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder={t('aiest.board.add_custom_placeholder', {
              defaultValue: 'e.g. install skirting boards',
            })}
            disabled={busy}
            className="h-9 flex-1 rounded-lg border border-border bg-surface-primary px-3 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          />
          <Button
            variant="secondary"
            size="md"
            icon={<Plus size={14} />}
            onClick={addCustom}
            disabled={busy || !customText.trim()}
          >
            {t('aiest.board.add', { defaultValue: 'Add' })}
          </Button>
        </div>
      </div>

      {/* Footer summary + confirm. */}
      <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-content-secondary">
          {t('aiest.board.summary', {
            defaultValue:
              '{{total}} work packages, {{grounded}} grounded, {{weak}} weak, {{gap}} gap. Confirm to match rates.',
            total: tally.total,
            grounded: tally.grounded,
            weak: tally.weak,
            gap: tally.gap,
          })}
          {tally.gap > 0 && (
            <span className="ml-1 text-[#b45309]">
              {t('aiest.board.gap_hint', {
                defaultValue:
                  'Gaps mean the catalogue for your currency is thin on that trade; switch catalogue or add a manual rate later.',
              })}
            </span>
          )}
        </p>
        <Button
          variant="primary"
          size="lg"
          loading={finishing}
          onClick={onFinish}
          icon={<Check size={16} />}
          disabled={busy || tally.total === 0}
        >
          {t('aiest.board.confirm', { defaultValue: 'Confirm group board' })}
        </Button>
      </div>
    </div>
  );
}

interface PackageRowProps {
  pkg: ComposedPackage;
  onToggle: (selected: boolean) => void;
  onRemove: () => void;
  disabled?: boolean;
}

function PackageRow({ pkg, onToggle, onRemove, disabled }: PackageRowProps) {
  const { t } = useTranslation();
  const cov = coverageLabel(pkg.coverage);
  const variant = coverageVariant(pkg.coverage);
  const label = t(`aiest.pkg.${pkg.package_key}`, { defaultValue: pkg.package_key });
  const trade = t(`aiest.trade.${pkg.trade}`, { defaultValue: pkg.trade });

  return (
    <li
      className={clsx(
        'flex items-center gap-3 rounded-lg border px-3 py-2 transition',
        pkg.selected
          ? 'border-border bg-surface-primary'
          : 'border-dashed border-border bg-surface-secondary/40 opacity-70',
      )}
    >
      <input
        type="checkbox"
        checked={pkg.selected}
        disabled={disabled}
        onChange={(e) => onToggle(e.target.checked)}
        aria-label={t('aiest.board.include', { defaultValue: 'Include {{name}}', name: label })}
        className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/40"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-content-primary">{label}</span>
          <Badge variant="neutral" size="sm">
            {trade}
          </Badge>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-content-tertiary">
          <span className={clsx(pkg.estimated && 'border-b border-dashed border-content-tertiary')}>
            {formatNumber(pkg.quantity)} {pkg.unit}
          </span>
          {pkg.estimated && (
            <span className="text-content-tertiary">
              {t('aiest.board.estimated', { defaultValue: 'estimated' })}
            </span>
          )}
        </div>
      </div>
      <span
        title={t('aiest.board.probe_score', {
          defaultValue: 'Probe score: {{score}}',
          score: scorePercent(pkg.best_score),
        })}
      >
        <Badge variant={variant} size="sm">
          {t(cov.i18nKey, { defaultValue: cov.defaultValue })}
        </Badge>
      </span>
      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        aria-label={t('aiest.board.remove', { defaultValue: 'Remove {{name}}', name: label })}
        className="rounded-md p-1 text-content-tertiary transition hover:bg-semantic-error-bg hover:text-semantic-error"
      >
        <Trash2 size={14} />
      </button>
    </li>
  );
}
