/**
 * `<CanvasToolbar>` — top bar above the EAC block canvas.
 *
 * Buttons (left → right):
 *   - Undo / Redo — bound to the store history.
 *   - Fit view — calls into xyflow via the prop callback (the canvas
 *     wires it to `useReactFlow().fitView`).
 *   - Save layout — fires `onSave`; the page persists to backend.
 *   - Run validation — fires `onValidate`; backend `compile_plan`.
 *   - Compile — fires `onCompile`; backend `describe_plan`.
 *
 * The toolbar is intentionally dumb — it doesn't talk to the store directly
 * for the action buttons, only for `canUndo`/`canRedo`. This keeps the page
 * in control of side effects (network, dirty state).
 */
import clsx from 'clsx';
import {
  Check,
  Maximize2,
  Play,
  Redo2,
  Save,
  Undo2,
  Zap,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
  selectCanRedo,
  selectCanUndo,
  useBlockCanvasStore,
} from './useBlockCanvasStore';

export interface CanvasToolbarProps {
  /** Called when the user clicks "fit view". */
  onFitView?: () => void;
  /** Called when the user clicks "save layout". */
  onSave?: () => void;
  /** Called when the user clicks "run validation". */
  onValidate?: () => void;
  /** Called when the user clicks "compile". */
  onCompile?: () => void;
  /** True while a long-running action is in flight (disables CTA buttons). */
  busy?: boolean;
  testId?: string;
}

interface ToolbarButtonProps {
  label: string;
  testId: string;
  icon: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'default' | 'primary' | 'success';
}

function ToolbarButton({ label, testId, icon, onClick, disabled, variant = 'default' }: ToolbarButtonProps) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={clsx(
        'inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium',
        'transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        variant === 'primary' &&
          'border-oe-blue bg-oe-blue text-white hover:bg-oe-blue/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        variant === 'success' &&
          'border-emerald-500 bg-emerald-500 text-white hover:bg-emerald-600',
        variant === 'default' &&
          'border-border bg-surface-primary text-content-primary hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30',
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function CanvasToolbar({
  onFitView,
  onSave,
  onValidate,
  onCompile,
  busy = false,
  testId,
}: CanvasToolbarProps) {
  const { t } = useTranslation();
  const undo = useBlockCanvasStore((s) => s.undo);
  const redo = useBlockCanvasStore((s) => s.redo);
  const canUndo = useBlockCanvasStore(selectCanUndo);
  const canRedo = useBlockCanvasStore(selectCanRedo);

  return (
    <div
      role="toolbar"
      aria-label={t('eac.canvas.toolbar', { defaultValue: 'Canvas toolbar' })}
      data-testid={testId ?? 'eac-canvas-toolbar'}
      className="flex h-11 items-center gap-2 border-b border-border bg-surface-primary px-3"
    >
      <div className="flex items-center gap-1">
        <ToolbarButton
          label={t('eac.canvas.undo', { defaultValue: 'Undo' })}
          testId="eac-canvas-undo"
          icon={<Undo2 size={14} aria-hidden="true" />}
          onClick={undo}
          disabled={!canUndo}
        />
        <ToolbarButton
          label={t('eac.canvas.redo', { defaultValue: 'Redo' })}
          testId="eac-canvas-redo"
          icon={<Redo2 size={14} aria-hidden="true" />}
          onClick={redo}
          disabled={!canRedo}
        />
      </div>

      <span className="h-6 w-px bg-border" aria-hidden="true" />

      <ToolbarButton
        label={t('eac.canvas.fitView', { defaultValue: 'Fit view' })}
        testId="eac-canvas-fit-view"
        icon={<Maximize2 size={14} aria-hidden="true" />}
        onClick={onFitView}
      />

      <span className="ml-auto h-6 w-px bg-border" aria-hidden="true" />

      <ToolbarButton
        label={t('eac.canvas.save', { defaultValue: 'Save layout' })}
        testId="eac-canvas-save"
        icon={<Save size={14} aria-hidden="true" />}
        onClick={onSave}
        disabled={busy}
      />
      <ToolbarButton
        label={t('eac.canvas.validate', { defaultValue: 'Validate' })}
        testId="eac-canvas-validate"
        icon={<Check size={14} aria-hidden="true" />}
        onClick={onValidate}
        disabled={busy}
        variant="success"
      />
      <ToolbarButton
        label={t('eac.canvas.compile', { defaultValue: 'Compile' })}
        testId="eac-canvas-compile"
        icon={busy ? <Zap size={14} className="animate-pulse" aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
        onClick={onCompile}
        disabled={busy}
        variant="primary"
      />
    </div>
  );
}

export default CanvasToolbar;
