// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Every word the cost control page says about a forecast source, a cost stage
// or a finding lives here, so the page, the drawer and the dialogs say the same
// thing in every language.
import type { TFunction } from 'i18next';

import { fmtNumber } from '@/shared/lib/formatters';
import type {
  CostControlFinding,
  CostStage,
  EvidenceKind,
  ExportKind,
  ForecastMethod,
  ForecastSource,
  LadderCause,
  PhaseLayer,
  SnapshotStatus,
} from './api';

/** Short name of a forecast method. */
export function methodLabel(t: TFunction, method: ForecastMethod | string): string {
  switch (method) {
    case 'maximum':
      return t('cost_control.method_maximum', { defaultValue: 'Maximum value' });
    case 'evm_cpi':
      return t('cost_control.method_evm_cpi', { defaultValue: 'Projected from progress (CPI)' });
    case 'manual':
      return t('cost_control.method_manual', { defaultValue: 'Manual' });
    default:
      return t('cost_control.method_best_available', { defaultValue: 'Best available source' });
  }
}

/** What a method does, in the words a site manager uses. */
export function methodHelp(t: TFunction, method: ForecastMethod | string): string {
  switch (method) {
    case 'maximum':
      return t('cost_control.method_maximum_help', {
        defaultValue:
          'Each line takes its highest figure: budget, estimate, award, measured or invoiced. Careful by design: a risk is never hidden behind a lower number.',
      });
    case 'evm_cpi':
      return t('cost_control.method_evm_cpi_help', {
        defaultValue:
          'If half the work is done and it cost 10% more than planned, the rest will likely cost 10% more too. Needs measured work and invoices on the line.',
      });
    case 'manual':
      return t('cost_control.method_manual_help', {
        defaultValue: 'You type the expected final cost of a line yourself, with a reason and the document behind it.',
      });
    default:
      return t('cost_control.method_best_available_help', {
        defaultValue:
          'Each line takes its most reliable figure: the final account, else the measured work, else the award plus changes, else the estimate, else the budget.',
      });
  }
}

/** When a method is the right choice, one short sentence. */
export function methodWhen(t: TFunction, method: ForecastMethod | string): string {
  switch (method) {
    case 'maximum':
      return t('cost_control.method_maximum_when', {
        defaultValue: 'Use it when the client wants the cautious figure, or while claims are open.',
      });
    case 'evm_cpi':
      return t('cost_control.method_evm_cpi_when', {
        defaultValue: 'Use it once work is well under way and progress is measured regularly.',
      });
    case 'manual':
      return t('cost_control.method_manual_when', {
        defaultValue: 'Use it on a line where you know more than the data, for example a new offer.',
      });
    default:
      return t('cost_control.method_best_available_when', {
        defaultValue: 'The usual choice. It follows the project as it matures, with nothing to type in.',
      });
  }
}

/** Why a line moved between two snapshots. */
export function causeLabel(t: TFunction, cause: LadderCause): string {
  switch (cause) {
    case 'new':
      return t('cost_control.cause_new', { defaultValue: 'New line' });
    case 'removed':
      return t('cost_control.cause_removed', { defaultValue: 'Line removed' });
    case 'method':
      return t('cost_control.cause_method', { defaultValue: 'Method changed' });
    case 'source':
      return t('cost_control.cause_source', { defaultValue: 'More mature figure' });
    default:
      return t('cost_control.cause_value', { defaultValue: 'Figure moved' });
  }
}

export function evidenceKindLabel(t: TFunction, kind: EvidenceKind | string): string {
  switch (kind) {
    case 'minutes':
      return t('cost_control.evidence_minutes', { defaultValue: 'Minutes' });
    case 'other':
      return t('cost_control.evidence_other', { defaultValue: 'Other' });
    default:
      return t('cost_control.evidence_document', { defaultValue: 'Document' });
  }
}

export function snapshotStatusLabel(t: TFunction, status: SnapshotStatus | 'live' | string): string {
  switch (status) {
    case 'draft':
      return t('cost_control.status_draft', { defaultValue: 'Draft' });
    case 'live':
      return t('cost_control.status_live', { defaultValue: 'Today' });
    default:
      return t('cost_control.status_frozen', { defaultValue: 'Frozen' });
  }
}

/** Column heading of one layer of the phase comparison. */
export function layerLabel(t: TFunction, layer: PhaseLayer): string {
  switch (layer) {
    case 'budget':
      return t('cost_control.layer_budget', { defaultValue: 'Budget' });
    case 'estimate':
      return t('cost_control.layer_estimate', { defaultValue: 'Estimate' });
    case 'tender':
      return t('cost_control.layer_tender', { defaultValue: 'Best tender' });
    case 'awarded':
      return t('cost_control.layer_awarded', { defaultValue: 'Awarded' });
    case 'changes':
      return t('cost_control.layer_changes', { defaultValue: 'Approved changes' });
    case 'committed':
      return t('cost_control.layer_committed', { defaultValue: 'Committed' });
    case 'pending':
      return t('cost_control.layer_pending', { defaultValue: 'Pending changes' });
    case 'measured':
      return t('cost_control.layer_measured', { defaultValue: 'Measured' });
    case 'certified':
      return t('cost_control.layer_certified', { defaultValue: 'Certified' });
    case 'invoiced':
      return t('cost_control.layer_invoiced', { defaultValue: 'Invoiced' });
    case 'paid':
      return t('cost_control.layer_paid', { defaultValue: 'Paid' });
    default:
      return t('cost_control.layer_forecast', { defaultValue: 'Forecast' });
  }
}

export function exportKindLabel(t: TFunction, kind: ExportKind): string {
  switch (kind) {
    case 'phase_comparison':
      return t('cost_control.export_phase_comparison', { defaultValue: 'Phase comparison' });
    case 'invoice_ledger':
      return t('cost_control.export_invoice_ledger', { defaultValue: 'Invoice ledger' });
    case 'forecast_documentation':
      return t('cost_control.export_forecast_documentation', { defaultValue: 'Forecast documentation' });
    default:
      return t('cost_control.export_cost_report', { defaultValue: 'Cost report' });
  }
}

/** Short name of where a forecast came from. */
export function sourceLabel(t: TFunction, source: ForecastSource): string {
  switch (source) {
    case 'budget':
      return t('cost_control.source_budget', { defaultValue: 'Budget' });
    case 'estimate':
      return t('cost_control.source_estimate', { defaultValue: 'Estimate' });
    case 'partly_awarded':
      return t('cost_control.source_partly_awarded', { defaultValue: 'Plan, partly awarded' });
    case 'awarded':
      return t('cost_control.source_awarded', { defaultValue: 'Award + changes' });
    case 'measured':
      return t('cost_control.source_measured', { defaultValue: 'Measured work' });
    case 'final':
      return t('cost_control.source_final', { defaultValue: 'Final account' });
    case 'manual':
      return t('cost_control.source_manual', { defaultValue: 'Your forecast' });
    case 'invoiced':
      return t('cost_control.source_invoiced', { defaultValue: 'Invoiced' });
    case 'evm':
      return t('cost_control.source_evm', { defaultValue: 'Projected from progress' });
    default:
      return t('cost_control.source_none', { defaultValue: 'No figure yet' });
  }
}

/** One sentence on why that source was taken, for the line drawer. */
export function sourceExplanation(t: TFunction, source: ForecastSource): string {
  switch (source) {
    case 'budget':
      return t('cost_control.source_budget_why', {
        defaultValue: 'Nothing is estimated or awarded on this line yet, so the budget is the best figure.',
      });
    case 'estimate':
      return t('cost_control.source_estimate_why', {
        defaultValue: 'Nothing is awarded on this line yet, so the estimate is the best figure.',
      });
    case 'partly_awarded':
      return t('cost_control.source_partly_awarded_why', {
        defaultValue:
          'Less than half of the plan is awarded so far, so the plan stays the forecast until more is let. If you know what the rest will cost, enter your own forecast.',
      });
    case 'awarded':
      return t('cost_control.source_awarded_why', {
        defaultValue: 'The work is awarded, so the contract value plus approved changes is the best figure.',
      });
    case 'measured':
      return t('cost_control.source_measured_why', {
        defaultValue: 'Certified work already exceeds the award plus changes, so the certified amount is the best figure.',
      });
    case 'final':
      return t('cost_control.source_final_why', {
        defaultValue: 'Every contract on this line is completed, so the certified amount is the final cost.',
      });
    case 'manual':
      return t('cost_control.source_manual_why', {
        defaultValue: 'Someone entered their own forecast with a reason. It stays until it is removed.',
      });
    case 'invoiced':
      return t('cost_control.source_invoiced_why', {
        defaultValue: 'The invoices on this line are the highest figure it has, so the maximum method takes them.',
      });
    case 'evm':
      return t('cost_control.source_evm_why', {
        defaultValue:
          'The cost at completion is projected from progress: what was spent so far, divided by the share of the work done.',
      });
    default:
      return t('cost_control.source_none_why', { defaultValue: 'This line has no money on it yet.' });
  }
}

/** Colour of the source chip: grey for the plan, blue to green as the figure matures. */
export function sourceTone(source: ForecastSource): string {
  switch (source) {
    case 'budget':
      return 'bg-surface-secondary text-content-secondary';
    case 'estimate':
      return 'bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300';
    case 'partly_awarded':
      return 'bg-sky-50 text-indigo-700 ring-1 ring-inset ring-indigo-200 dark:bg-sky-950/40 dark:text-indigo-300 dark:ring-indigo-800';
    case 'awarded':
      return 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300';
    case 'measured':
      return 'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300';
    case 'final':
      return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300';
    case 'manual':
      return 'bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-300';
    case 'invoiced':
      return 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300';
    case 'evm':
      return 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300';
    default:
      return 'bg-surface-secondary text-content-tertiary';
  }
}

/** The order the "how it works" legend lists the sources in: most reliable first. */
export const SOURCE_PRIORITY: ForecastSource[] = ['final', 'measured', 'awarded', 'estimate', 'budget'];

export function stageLabel(t: TFunction, stage: CostStage | string): string {
  switch (stage) {
    case 'budget':
      return t('cost_control.stage_budget', { defaultValue: 'Budget' });
    case 'estimate':
      return t('cost_control.stage_estimate', { defaultValue: 'Estimate' });
    case 'detailed_estimate':
      return t('cost_control.stage_detailed_estimate', { defaultValue: 'Detailed estimate' });
    case 'pre_tender':
      return t('cost_control.stage_pre_tender', { defaultValue: 'Pre-tender estimate' });
    case 'award':
      return t('cost_control.stage_award', { defaultValue: 'Award' });
    case 'final':
      return t('cost_control.stage_final', { defaultValue: 'Final account' });
    default:
      return t('cost_control.stage_forecast', { defaultValue: 'Forecast' });
  }
}

/** The same stage under the national schemes, so every user finds their own word. */
export function stageHint(t: TFunction, stage: CostStage | string): string {
  switch (stage) {
    case 'budget':
      return t('cost_control.stage_budget_hint', {
        defaultValue: 'DIN 276 Kostenrahmen · RIBA 0-1 order of cost estimate · AACE class 5',
      });
    case 'estimate':
      return t('cost_control.stage_estimate_hint', {
        defaultValue: 'DIN 276 Kostenschätzung · RIBA 2 cost plan 1 · AACE class 4',
      });
    case 'detailed_estimate':
      return t('cost_control.stage_detailed_estimate_hint', {
        defaultValue: 'DIN 276 Kostenberechnung · RIBA 3 cost plan 2 · AACE class 3',
      });
    case 'pre_tender':
      return t('cost_control.stage_pre_tender_hint', {
        defaultValue: 'DIN 276 Kostenvoranschlag · RIBA 4 pre-tender estimate · AACE class 2',
      });
    case 'award':
      return t('cost_control.stage_award_hint', {
        defaultValue: 'DIN 276 Kostenanschlag · contract sum · AACE class 1',
      });
    case 'final':
      return t('cost_control.stage_final_hint', {
        defaultValue: 'DIN 276 Kostenfeststellung · final account',
      });
    default:
      return t('cost_control.stage_forecast_hint', {
        defaultValue: 'Monthly cost report during construction',
      });
  }
}

/** Plain-language title of a finding. */
export function findingTitle(t: TFunction, finding: CostControlFinding): string {
  const d = finding.details;
  switch (finding.rule_id) {
    case 'cost_control.unassigned_money':
      return t('cost_control.finding_unassigned', {
        defaultValue: 'Committed money is not on any cost line',
      });
    case 'cost_control.certified_over_committed':
      return t('cost_control.finding_certified_over', {
        defaultValue: '{{code}}: more certified than awarded plus changes',
        code: finding.code,
      });
    case 'cost_control.forecast_over_plan':
      return t('cost_control.finding_over_plan', {
        defaultValue: '{{code}}: forecast {{pct}}% above plan',
        code: finding.code,
        pct: d.pct ? fmtNumber(d.pct, 1) : '',
      });
    case 'cost_control.partly_awarded':
      return t('cost_control.finding_partly_awarded', {
        defaultValue: '{{code}}: only {{pct}}% of the plan is awarded',
        code: finding.code,
        // The share arrives as a whole percent.
        pct: d.pct ? fmtNumber(d.pct, 0) : '',
      });
    case 'cost_control.pending_changes':
      return t('cost_control.finding_pending', {
        defaultValue: 'Change orders waiting for a decision: {{n}}',
        n: Number(d.count ?? 0),
      });
    case 'cost_control.snapshot_stale':
      return d.days
        ? t('cost_control.finding_stale', {
            defaultValue: 'Days since the last saved forecast: {{n}}',
            n: Number(d.days),
          })
        : t('cost_control.finding_never_saved', { defaultValue: 'No forecast saved yet' });
    default:
      return finding.rule_id;
  }
}

/** What to do about a finding, one short sentence. */
export function findingHint(t: TFunction, finding: CostControlFinding): string {
  switch (finding.rule_id) {
    case 'cost_control.unassigned_money':
      return t('cost_control.finding_unassigned_hint', {
        defaultValue: 'Link the contract or order lines to cost lines, so the money shows where it belongs.',
      });
    case 'cost_control.certified_over_committed':
      return t('cost_control.finding_certified_over_hint', {
        defaultValue: 'Approve the change that covers the extra work, or check the claim.',
      });
    case 'cost_control.forecast_over_plan':
      return t('cost_control.finding_over_plan_hint', {
        defaultValue: 'Open the line to see where the figure comes from.',
      });
    case 'cost_control.partly_awarded':
      return t('cost_control.finding_partly_awarded_hint', {
        defaultValue: 'If more work is still to be let here, enter your own forecast.',
      });
    case 'cost_control.pending_changes':
      return t('cost_control.finding_pending_hint', {
        defaultValue: 'They are not in the forecast until approved.',
      });
    case 'cost_control.snapshot_stale':
      return t('cost_control.finding_stale_hint', {
        defaultValue: 'Save the forecast once a month so you can see how the cost moved.',
      });
    default:
      return '';
  }
}
