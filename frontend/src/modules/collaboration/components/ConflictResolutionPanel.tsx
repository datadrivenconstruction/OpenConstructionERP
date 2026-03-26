import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { GitMerge, X, User, Clock, AlertTriangle, CheckCircle2, Edit3 } from 'lucide-react';
import clsx from 'clsx';
import type { ConflictItem, ConflictResolution } from '../hooks/useConflictDetection';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConflictResolutionPanelProps {
  /** List of unresolved conflicts to display */
  conflicts: ConflictItem[];
  /** Called when the user picks a resolution strategy for a conflict */
  onResolve: (id: string, resolution: ConflictResolution, manualValue?: string) => void;
  /** Called when the user dismisses the panel without resolving all conflicts */
  onDismiss: () => void;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * ConflictResolutionPanel
 *
 * A fixed overlay panel that surfaces Yjs CRDT merge conflicts to the user.
 * Each conflict shows the local pending value next to the incoming remote value
 * and offers three resolution paths:
 *   - "Keep mine"       → discard remote change
 *   - "Accept theirs"   → adopt remote change
 *   - "Manual merge"    → user types a custom merged value
 *
 * The panel is rendered only when `conflicts` is non-empty.
 */
export function ConflictResolutionPanel({
  conflicts,
  onResolve,
  onDismiss,
}: ConflictResolutionPanelProps) {
  const { t } = useTranslation();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [manualValue, setManualValue] = useState('');
  const [manualMode, setManualMode] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const manualInputRef = useRef<HTMLTextAreaElement>(null);

  // Reset state when the active conflict changes
  const activeConflict = conflicts[Math.min(currentIndex, conflicts.length - 1)];

  useEffect(() => {
    setManualValue('');
    setManualMode(false);
  }, [activeConflict?.id]);

  // Clamp index when conflicts list shrinks
  useEffect(() => {
    if (currentIndex >= conflicts.length && conflicts.length > 0) {
      setCurrentIndex(conflicts.length - 1);
    }
  }, [conflicts.length, currentIndex]);

  // Focus manual input when entering manual mode
  useEffect(() => {
    if (manualMode) {
      manualInputRef.current?.focus();
    }
  }, [manualMode]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onDismiss();
      }
    };
    document.addEventListener('keydown', handler, { capture: true });
    return () => document.removeEventListener('keydown', handler, { capture: true });
  }, [onDismiss]);

  // Close on backdrop click
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        onDismiss();
      }
    },
    [onDismiss],
  );

  if (!conflicts.length) return null;

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleResolve = (resolution: ConflictResolution) => {
    if (!activeConflict) return;
    if (resolution === 'manual') {
      if (!manualMode) {
        setManualMode(true);
        return;
      }
      onResolve(activeConflict.id, 'manual', manualValue);
    } else {
      onResolve(activeConflict.id, resolution);
    }
    // If more conflicts remain, keep panel open at same (now clamped) index
  };

  const handleAcceptManual = () => {
    if (!activeConflict) return;
    onResolve(activeConflict.id, 'manual', manualValue);
  };

  // ---------------------------------------------------------------------------
  // Derived values
  // ---------------------------------------------------------------------------

  const total = conflicts.length;
  const position = Math.min(currentIndex, total - 1);
  const isLast = position === total - 1;

  const formattedTime = activeConflict
    ? activeConflict.timestamp.toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    : '';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label={t('conflict.panel_aria_label', { defaultValue: 'Conflict resolution panel' })}
    >
      <div
        ref={panelRef}
        className={clsx(
          'relative z-10 w-full max-w-2xl mx-4',
          'rounded-2xl border border-border-light',
          'bg-surface-elevated shadow-2xl',
          'animate-scale-in',
          'focus:outline-none',
        )}
        tabIndex={-1}
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 dark:bg-amber-900/30">
              <GitMerge className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-content-primary">
                {t('conflict.panel_title', { defaultValue: 'Merge Conflict Detected' })}
              </h2>
              <p className="text-xs text-content-tertiary">
                {t('conflict.panel_subtitle', {
                  defaultValue: 'A remote collaborator edited the same field. Choose how to resolve.',
                })}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Conflict counter */}
            {total > 1 && (
              <span className="text-xs font-medium text-content-secondary">
                {position + 1} / {total}
              </span>
            )}
            <button
              onClick={onDismiss}
              aria-label={t('common.close', { defaultValue: 'Close' })}
              className="p-1.5 rounded-lg hover:bg-surface-secondary text-content-tertiary transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ── Conflict info bar ── */}
        {activeConflict && (
          <div className="flex flex-wrap items-center gap-4 px-6 py-3 bg-surface-secondary text-xs text-content-tertiary border-b border-border">
            <span className="flex items-center gap-1.5">
              <AlertTriangle size={12} className="text-amber-500" />
              <span className="font-mono font-medium text-content-secondary">
                {activeConflict.positionOrdinal}
              </span>
              <span>·</span>
              <span>{activeConflict.field}</span>
            </span>
            <span className="flex items-center gap-1.5">
              <User size={12} />
              {t('conflict.changed_by', { defaultValue: 'Changed by' })}{' '}
              <strong className="text-content-secondary">{activeConflict.remoteUser}</strong>
            </span>
            <span className="flex items-center gap-1.5">
              <Clock size={12} />
              {formattedTime}
            </span>
          </div>
        )}

        {/* ── Side-by-side values ── */}
        {activeConflict && (
          <div className="grid grid-cols-2 gap-4 px-6 py-5">
            {/* Local value */}
            <ValueCard
              label={t('conflict.your_version', { defaultValue: 'Your version' })}
              value={activeConflict.localValue}
              variant="local"
              action={
                <button
                  onClick={() => handleResolve('keep_mine')}
                  data-testid="btn-keep-mine"
                  className={clsx(
                    'w-full mt-3 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                    'bg-oe-blue text-white hover:bg-oe-blue-hover',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
                  )}
                >
                  {t('conflict.keep_mine', { defaultValue: 'Keep mine' })}
                </button>
              }
            />

            {/* Remote value */}
            <ValueCard
              label={t('conflict.their_version', {
                defaultValue: 'Their version',
              })}
              sublabel={activeConflict.remoteUser}
              value={activeConflict.remoteValue}
              variant="remote"
              action={
                <button
                  onClick={() => handleResolve('accept_theirs')}
                  data-testid="btn-accept-theirs"
                  className={clsx(
                    'w-full mt-3 rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                    'bg-surface-primary text-content-primary border border-border',
                    'hover:bg-surface-secondary',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-2',
                  )}
                >
                  {t('conflict.accept_theirs', { defaultValue: 'Accept theirs' })}
                </button>
              }
            />
          </div>
        )}

        {/* ── Manual merge section ── */}
        {activeConflict && (
          <div className="px-6 pb-5">
            {!manualMode ? (
              <button
                onClick={() => setManualMode(true)}
                data-testid="btn-manual-merge"
                className={clsx(
                  'flex items-center gap-2 text-xs font-medium transition-colors',
                  'text-content-tertiary hover:text-content-primary',
                )}
              >
                <Edit3 size={12} />
                {t('conflict.manual_merge', { defaultValue: 'Manual merge...' })}
              </button>
            ) : (
              <div className="space-y-2">
                <label className="block text-xs font-medium text-content-secondary">
                  {t('conflict.manual_label', { defaultValue: 'Enter merged value' })}
                </label>
                <textarea
                  ref={manualInputRef}
                  value={manualValue}
                  onChange={(e) => setManualValue(e.target.value)}
                  rows={3}
                  data-testid="manual-merge-input"
                  placeholder={t('conflict.manual_placeholder', {
                    defaultValue: 'Type the merged value...',
                  })}
                  className={clsx(
                    'w-full rounded-lg border border-border bg-surface-secondary',
                    'px-3 py-2 text-xs text-content-primary resize-none',
                    'placeholder:text-content-quaternary',
                    'focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-oe-blue',
                  )}
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleAcceptManual}
                    disabled={!manualValue.trim()}
                    data-testid="btn-apply-manual"
                    className={clsx(
                      'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
                      'bg-emerald-500 text-white hover:bg-emerald-600',
                      'disabled:opacity-40 disabled:pointer-events-none',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2',
                    )}
                  >
                    <CheckCircle2 size={12} />
                    {t('conflict.apply_merged', { defaultValue: 'Apply merged value' })}
                  </button>
                  <button
                    onClick={() => {
                      setManualMode(false);
                      setManualValue('');
                    }}
                    className="text-xs text-content-tertiary hover:text-content-primary transition-colors"
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Navigation footer (only when multiple conflicts) ── */}
        {total > 1 && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-border bg-surface-secondary rounded-b-2xl">
            <button
              type="button"
              onClick={() => setCurrentIndex((i) => Math.max(0, i - 1))}
              disabled={position === 0}
              aria-disabled={position === 0}
              className={clsx(
                'text-xs text-content-secondary hover:text-content-primary transition-colors',
                'disabled:opacity-30 disabled:cursor-not-allowed',
              )}
            >
              ← {t('conflict.previous', { defaultValue: 'Previous' })}
            </button>

            {/* Dot indicators */}
            <div className="flex items-center gap-1.5">
              {conflicts.map((c, i) => (
                <button
                  key={c.id}
                  onClick={() => setCurrentIndex(i)}
                  aria-label={`${t('conflict.conflict_number', { defaultValue: 'Conflict' })} ${i + 1}`}
                  className={clsx(
                    'h-1.5 rounded-full transition-all',
                    i === position
                      ? 'w-4 bg-oe-blue'
                      : 'w-1.5 bg-border hover:bg-content-tertiary',
                  )}
                />
              ))}
            </div>

            <button
              type="button"
              onClick={() => setCurrentIndex((i) => Math.min(total - 1, i + 1))}
              disabled={isLast}
              aria-disabled={isLast}
              className={clsx(
                'text-xs text-content-secondary hover:text-content-primary transition-colors',
                'disabled:opacity-30 disabled:cursor-not-allowed',
              )}
            >
              {t('conflict.next', { defaultValue: 'Next' })} →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ValueCard sub-component
// ---------------------------------------------------------------------------

interface ValueCardProps {
  label: string;
  sublabel?: string;
  value: string;
  variant: 'local' | 'remote';
  action: React.ReactNode;
}

function ValueCard({ label, sublabel, value, variant, action }: ValueCardProps) {
  const borderColor = variant === 'local' ? 'border-oe-blue/40' : 'border-border';
  const headerBg = variant === 'local' ? 'bg-blue-50 dark:bg-blue-900/20' : 'bg-surface-secondary';
  const labelColor =
    variant === 'local' ? 'text-oe-blue font-semibold' : 'text-content-secondary font-medium';

  return (
    <div className={clsx('rounded-xl border overflow-hidden', borderColor)}>
      {/* Card header */}
      <div className={clsx('flex items-center gap-1.5 px-3 py-2', headerBg)}>
        <span className={clsx('text-xs', labelColor)}>{label}</span>
        {sublabel && (
          <span className="text-xs text-content-tertiary truncate">· {sublabel}</span>
        )}
      </div>

      {/* Value display */}
      <div className="px-3 py-3">
        <pre
          data-testid={`value-${variant}`}
          className={clsx(
            'text-xs leading-relaxed whitespace-pre-wrap break-words font-mono',
            'text-content-primary min-h-[3rem] max-h-32 overflow-y-auto',
          )}
        >
          {value || <span className="text-content-quaternary italic">—</span>}
        </pre>
        {action}
      </div>
    </div>
  );
}
