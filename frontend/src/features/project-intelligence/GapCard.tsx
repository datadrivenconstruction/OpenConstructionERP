/**
 * GapCard — displays a critical gap with severity badge, action button, and expand.
 *
 * Severity is indicated by both color and icon to maintain accessibility.
 */

import clsx from 'clsx';
import {
  AlertOctagon,
  AlertTriangle,
  AlertCircle,
  Info,
  ChevronRight,
  Zap,
} from 'lucide-react';

interface CriticalGap {
  id: string;
  domain: string;
  severity: string;
  title: string;
  description: string;
  impact: string;
  action_id: string | null;
  affected_count: number | null;
}

interface GapCardProps {
  gap: CriticalGap;
  isExpanded: boolean;
  onToggle: () => void;
  onAction?: () => void;
  actionLabel?: string;
}

const SEVERITY_CONFIG: Record<
  string,
  { color: string; bg: string; border: string; icon: typeof AlertOctagon; label: string }
> = {
  blocker: {
    color: 'text-red-400',
    bg: 'bg-red-500/10',
    border: 'border-l-red-500',
    icon: AlertOctagon,
    label: 'BLOCKER',
  },
  critical: {
    color: 'text-orange-400',
    bg: 'bg-orange-500/10',
    border: 'border-l-orange-500',
    icon: AlertTriangle,
    label: 'CRITICAL',
  },
  warning: {
    color: 'text-yellow-400',
    bg: 'bg-yellow-500/10',
    border: 'border-l-yellow-500',
    icon: AlertCircle,
    label: 'WARNING',
  },
  suggestion: {
    color: 'text-gray-400',
    bg: 'bg-gray-500/10',
    border: 'border-l-gray-500',
    icon: Info,
    label: 'SUGGESTION',
  },
};

export function GapCard({ gap, isExpanded, onToggle, onAction, actionLabel }: GapCardProps) {
  const config = SEVERITY_CONFIG[gap.severity] || SEVERITY_CONFIG.suggestion;
  const Icon = config?.icon;

  return (
    <div
      className={clsx(
        'rounded-lg border-l-[3px] transition-all duration-200',
        config?.border,
        isExpanded ? 'bg-surface-tertiary/70' : 'bg-surface-tertiary/30 hover:bg-surface-tertiary/50'
      )}
    >
      {/* Header — always visible */}
      <button
        onClick={onToggle}
        className="w-full text-left px-3 py-2.5 flex items-start gap-2"
        aria-expanded={isExpanded}
      >
        {Icon && <Icon size={14} className={clsx('shrink-0 mt-0.5', config?.color)} />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span
              className={clsx(
                'text-2xs font-bold uppercase tracking-wider px-1 py-0.5 rounded',
                config?.bg,
                config?.color
              )}
            >
              {config?.label}
            </span>
            <span className="text-2xs text-content-quaternary uppercase">
              {gap.domain}
            </span>
          </div>
          <p className="text-xs font-medium text-content-primary leading-snug">
            {gap.title}
          </p>
          {!isExpanded && (
            <p className="text-2xs text-content-tertiary mt-0.5 truncate">
              {gap.impact}
            </p>
          )}
        </div>
        <ChevronRight
          size={12}
          className={clsx(
            'shrink-0 mt-1.5 text-content-quaternary transition-transform',
            isExpanded && 'rotate-90'
          )}
        />
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-3 pb-3 pt-0 space-y-2">
          <p className="text-xs text-content-secondary">{gap.description}</p>
          <p className="text-xs text-content-tertiary">
            <strong className="text-content-secondary">Impact:</strong> {gap.impact}
          </p>
          {gap.affected_count != null && gap.affected_count > 0 && (
            <p className="text-xs text-content-tertiary">
              <strong className="text-content-secondary">Affected items:</strong>{' '}
              {gap.affected_count}
            </p>
          )}
          {onAction && actionLabel && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onAction();
              }}
              className="mt-1 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-oe-blue rounded-md hover:bg-oe-blue-dark transition-colors"
            >
              <Zap size={12} />
              {actionLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
