/**
 * DomainDetails — tabbed panel showing detailed metrics per domain.
 *
 * Each tab shows key metrics, status indicators, and action buttons.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Table2,
  ShieldCheck,
  CalendarDays,
  TrendingUp,
  Ruler,
  ShieldAlert,
  FileText,
  FolderOpen,
  FileBarChart,
  Zap,
  CheckCircle2,
  AlertTriangle,
  X as XIcon,
} from 'lucide-react';

// Domain tab config
const DOMAIN_TABS = [
  { id: 'boq', label: 'BOQ', icon: Table2, color: '#f0883e' },
  { id: 'validation', label: 'Validation', icon: ShieldCheck, color: '#3fb950' },
  { id: 'schedule', label: 'Schedule', icon: CalendarDays, color: '#58a6ff' },
  { id: 'cost_model', label: 'Cost Model', icon: TrendingUp, color: '#bc8cff' },
  { id: 'takeoff', label: 'Takeoff', icon: Ruler, color: '#39d353' },
  { id: 'risk', label: 'Risk', icon: ShieldAlert, color: '#ff7b72' },
  { id: 'tendering', label: 'Tendering', icon: FileText, color: '#ffa657' },
  { id: 'documents', label: 'Documents', icon: FolderOpen, color: '#79c0ff' },
  { id: 'reports', label: 'Reports', icon: FileBarChart, color: '#56d364' },
];

interface ActionDef {
  id: string;
  label: string;
  description: string;
  icon: string;
  navigate_to: string | null;
  has_backend_action: boolean;
}

/** Domain state map from backend API — each domain sub-object contains
 *  heterogeneous fields (numbers, strings, booleans, arrays). */
type DomainStateValue = string | number | boolean | string[] | null | undefined;
type DomainStateMap = Record<string, Record<string, DomainStateValue>> & { project_name?: string };

/** Safely extract a number from a domain state field, defaulting to 0. */
function n(val: DomainStateValue): number {
  return typeof val === 'number' ? val : 0;
}
/** Safely extract a string from a domain state field. */
function s(val: DomainStateValue): string {
  return typeof val === 'string' ? val : '';
}
/** Safely extract a string array from a domain state field. */
function arr(val: DomainStateValue): string[] {
  return Array.isArray(val) ? val : [];
}

interface DomainDetailsProps {
  state: DomainStateMap;
  scores: Record<string, number>;
  selectedDomain: string | null;
  onSelectDomain: (domain: string | null) => void;
  onAction: (actionId: string) => void;
  actions: ActionDef[];
}

export function DomainDetails({
  state,
  scores,
  selectedDomain,
  onSelectDomain,
  onAction,
  actions,
}: DomainDetailsProps) {
  const { t } = useTranslation();

  return (
    <div className="bg-surface-secondary rounded-xl border border-border-light overflow-hidden">
      {/* Tab bar */}
      <div className="flex overflow-x-auto border-b border-border-light px-2 pt-2 gap-0.5">
        {DOMAIN_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = selectedDomain === tab.id;
          const score = scores[tab.id] ?? 0;
          return (
            <button
              key={tab.id}
              onClick={() => onSelectDomain(isActive ? null : tab.id)}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-md transition-colors whitespace-nowrap',
                isActive
                  ? 'bg-surface-tertiary text-content-primary border-b-2'
                  : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-tertiary/50'
              )}
              style={isActive ? { borderBottomColor: tab.color } : undefined}
            >
              <Icon size={13} style={isActive ? { color: tab.color } : undefined} />
              {tab.label}
              <span className="text-2xs text-content-quaternary">{Math.round(score)}%</span>
            </button>
          );
        })}
      </div>

      {/* Detail content */}
      <div className="px-4 py-3">
        {!selectedDomain ? (
          <p className="text-xs text-content-tertiary text-center py-3">
            {t('project_intelligence.select_domain', {
              defaultValue: 'Select a domain tab above to see detailed metrics.',
            })}
          </p>
        ) : (
          <DomainContent
            domain={selectedDomain}
            state={state}
            score={scores[selectedDomain] ?? 0}
            onAction={onAction}
            actions={actions}
          />
        )}
      </div>
    </div>
  );
}

function DomainContent({
  domain,
  state,
  score,
  onAction,
  actions,
}: {
  domain: string;
  state: DomainStateMap;
  score: number;
  onAction: (actionId: string) => void;
  actions: ActionDef[];
}) {

  const rows: { label: string; value: string | number; status?: 'ok' | 'warn' | 'error' }[] = [];

  // Build metrics rows based on domain
  switch (domain) {
    case 'boq': {
      const b = state.boq || {};
      rows.push(
        { label: 'Total items', value: n(b.total_items) },
        { label: 'Sections', value: n(b.sections_count) },
        {
          label: 'With prices',
          value: n(b.total_items) - n(b.items_with_zero_price),
          status: n(b.items_with_zero_price) === 0 ? 'ok' : 'warn',
        },
        {
          label: 'Zero price',
          value: n(b.items_with_zero_price),
          status: n(b.items_with_zero_price) === 0 ? 'ok' : 'warn',
        },
        {
          label: 'Zero quantity',
          value: n(b.items_with_zero_quantity),
          status: n(b.items_with_zero_quantity) === 0 ? 'ok' : 'warn',
        },
        { label: 'Last modified', value: s(b.last_modified) ? _formatDate(s(b.last_modified)) : 'Never' },
        {
          label: 'Export ready',
          value: b.export_ready ? 'Yes' : 'No',
          status: b.export_ready ? 'ok' : 'warn',
        }
      );
      break;
    }
    case 'schedule': {
      const sc = state.schedule || {};
      rows.push(
        { label: 'Activities', value: n(sc.activities_count) },
        { label: 'Start date', value: s(sc.start_date) || 'Not set' },
        { label: 'End date', value: s(sc.end_date) || 'Not set' },
        { label: 'Duration', value: sc.duration_days != null ? `${sc.duration_days} days` : 'Unknown' },
        {
          label: 'Baseline set',
          value: sc.baseline_set ? 'Yes' : 'No',
          status: sc.baseline_set ? 'ok' : 'warn',
        },
        {
          label: 'Critical path',
          value: sc.has_critical_path ? 'Yes' : 'No',
          status: sc.has_critical_path ? 'ok' : undefined,
        }
      );
      break;
    }
    case 'validation': {
      const v = state.validation || {};
      rows.push(
        { label: 'Last run', value: s(v.last_run) ? _formatDate(s(v.last_run)) : 'Never' },
        {
          label: 'Errors',
          value: n(v.total_errors),
          status: n(v.total_errors) === 0 ? 'ok' : 'error',
        },
        {
          label: 'Warnings',
          value: n(v.warnings),
          status: n(v.warnings) === 0 ? 'ok' : 'warn',
        },
        { label: 'Passed rules', value: n(v.passed_rules), status: 'ok' },
        { label: 'Total rules', value: n(v.total_rules) }
      );
      break;
    }
    case 'risk': {
      const r = state.risk || {};
      rows.push(
        { label: 'Total risks', value: n(r.total_risks) },
        {
          label: 'High unmitigated',
          value: n(r.high_severity_unmitigated),
          status: n(r.high_severity_unmitigated) === 0 ? 'ok' : 'error',
        },
        {
          label: 'Contingency set',
          value: r.contingency_set ? 'Yes' : 'No',
          status: r.contingency_set ? 'ok' : 'warn',
        }
      );
      break;
    }
    case 'takeoff': {
      const tk = state.takeoff || {};
      rows.push(
        { label: 'Files uploaded', value: n(tk.files_uploaded) },
        { label: 'Files processed', value: n(tk.files_processed) },
        { label: 'Formats', value: arr(tk.formats).join(', ') || 'None' },
        { label: 'Quantities extracted', value: n(tk.quantities_extracted) }
      );
      break;
    }
    case 'cost_model': {
      const cm = state.cost_model || {};
      rows.push(
        {
          label: 'Budget set',
          value: cm.budget_set ? 'Yes' : 'No',
          status: cm.budget_set ? 'ok' : 'warn',
        },
        {
          label: 'Baseline exists',
          value: cm.baseline_exists ? 'Yes' : 'No',
          status: cm.baseline_exists ? 'ok' : 'warn',
        },
        {
          label: 'Actuals linked',
          value: cm.actuals_linked ? 'Yes' : 'No',
          status: cm.actuals_linked ? 'ok' : undefined,
        },
        {
          label: 'Earned value',
          value: cm.earned_value_active ? 'Active' : 'Inactive',
          status: cm.earned_value_active ? 'ok' : undefined,
        }
      );
      break;
    }
    case 'tendering': {
      const td = state.tendering || {};
      rows.push(
        { label: 'Bid packages', value: n(td.bid_packages) },
        { label: 'Bids received', value: n(td.bids_received) },
        {
          label: 'Bids compared',
          value: td.bids_compared ? 'Yes' : 'No',
          status: td.bids_compared ? 'ok' : undefined,
        }
      );
      break;
    }
    case 'documents': {
      const doc = state.documents || {};
      rows.push(
        { label: 'Total files', value: n(doc.total_files) },
        {
          label: 'Categories',
          value: arr(doc.categories_covered).join(', ') || 'None',
        }
      );
      break;
    }
    case 'reports': {
      const rep = state.reports || {};
      rows.push(
        { label: 'Reports generated', value: n(rep.reports_generated) },
        { label: 'Last report', value: s(rep.last_report) ? _formatDate(s(rep.last_report)) : 'Never' }
      );
      break;
    }
  }

  const domainConfig = DOMAIN_TABS.find((d) => d.id === domain);

  const domainActions = actions.filter((a) => _isActionForDomain(a, domain));

  return (
    <div>
      {/* Score bar — compact */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-semibold text-content-primary">
          {domainConfig?.label || domain}
        </span>
        <div className="flex-1 h-1.5 bg-border-light/40 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${score}%`,
              backgroundColor: domainConfig?.color || '#8b949e',
            }}
          />
        </div>
        <span className="text-xs font-semibold tabular-nums" style={{ color: domainConfig?.color }}>
          {Math.round(score)}%
        </span>
      </div>

      {/* Metrics — compact card grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 mb-3">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between gap-2 rounded-lg bg-surface-tertiary/50 px-2.5 py-1.5"
          >
            <span className="text-2xs text-content-tertiary truncate">{row.label}</span>
            <span className="text-xs font-medium text-content-secondary tabular-nums flex items-center gap-1 shrink-0">
              {String(row.value)}
              {row.status === 'ok' && <CheckCircle2 size={10} className="text-green-400" />}
              {row.status === 'warn' && <AlertTriangle size={10} className="text-yellow-400" />}
              {row.status === 'error' && <XIcon size={10} className="text-red-400" />}
            </span>
          </div>
        ))}
      </div>

      {/* Domain actions */}
      {domainActions.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-2 border-t border-border-light">
          {domainActions.map((action) => (
            <button
              key={action.id}
              onClick={() => onAction(action.id)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs text-content-secondary bg-surface-tertiary border border-border-light rounded-md hover:bg-surface-quaternary transition-colors"
            >
              <Zap size={11} />
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function _isActionForDomain(action: ActionDef, domain: string): boolean {
  // Map actions to domains based on their ID patterns
  const mapping: Record<string, string[]> = {
    boq: ['action_create_boq_ai', 'action_open_boq', 'action_match_cwicr_prices'],
    validation: ['action_run_validation', 'action_open_validation'],
    schedule: ['action_generate_schedule', 'action_link_schedule_boq'],
    risk: ['action_open_risks'],
  };
  return (mapping[domain] || []).includes(action.id);
}

function _formatDate(dateStr: string): string {
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    if (hours < 1) return 'just now';
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  } catch {
    return dateStr;
  }
}
