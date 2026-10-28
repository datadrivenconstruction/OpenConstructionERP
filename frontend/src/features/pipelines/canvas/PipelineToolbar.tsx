// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelineToolbar>` — sticky top bar above the pipeline canvas.
 *
 * Cloned from EAC `CanvasToolbar`: `role="toolbar"`, 32 px buttons,
 * default/primary/danger variants. Undo/Redo read the store directly; the
 * page owns the side-effecting actions (Save / Run / Stop) so dirty-state and
 * network stay in the page.
 */
import clsx from 'clsx';
import {
  EyeOff,
  FolderOpen,
  Maximize2,
  Redo2,
  Save,
  Sparkles,
  Undo2,
  Play,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ModuleGuideButton } from '@/shared/ui';

import {
  selectCanRedo,
  selectCanUndo,
  usePipelineStore,
} from '../usePipelineStore';
import { pipelinesGuide } from '../pipelinesGuide';

export interface PipelineToolbarProps {
  onFitView?: () => void;
  onSave?: () => void;
  onRun?: () => void;
  onStop?: () => void;
  onExplain?: () => void;
  /** Open the pipeline library (templates + saved workflows). */
  onOpenLibrary?: () => void;
  /** True while a save / run request is in flight. */
  busy?: boolean;
  /** True while a run is live (swaps Run for Stop affordance). */
  running?: boolean;
  /** Count of authoring-time issues; shows a warning chip when > 0. */
  issueCount?: number;
  /** True when there are unsaved edits; shows an "Unsaved changes" badge. */
  dirty?: boolean;
  testId?: string;
}

interface TBtnProps {
  label: string;
  testId: string;
  icon: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: 'default' | 'primary' | 'danger';
  /** Optional tooltip override; defaults to `label`. */
  title?: string;
}

function TBtn({ label, testId, icon, onClick, disabled, variant = 'default', title }: TBtnProps) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      title={title ?? label}
      aria-label={label}
      className={clsx(
        'inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium',
        'transition-colors disabled:cursor-not-allowed disabled:opacity-40',
        variant === 'primary' &&
          'border-oe-blue bg-oe-blue text-white hover:bg-oe-blue/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        variant === 'danger' &&
          'border-semantic-error bg-semantic-error text-white hover:opacity-90',
        variant === 'default' &&
          'border-border bg-surface-primary text-content-primary hover:bg-surface-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30',
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function PipelineToolbar({
  onFitView,
  onSave,
  onRun,
  onStop,
  onExplain,
  onOpenLibrary,
  busy = false,
  running = false,
  issueCount = 0,
  dirty = false,
  testId,
}: PipelineToolbarProps) {
  const { t } = useTranslation();
  const undo = usePipelineStore((s) => s.undo);
  const redo = usePipelineStore((s) => s.redo);
  const canUndo = usePipelineStore(selectCanUndo);
  const canRedo = usePipelineStore(selectCanRedo);

  return (
    <div
      role="toolbar"
      aria-label={t('pipeline.toolbar.aria', {
        defaultValue: 'Pipeline toolbar',
      })}
      data-testid={testId ?? 'pipeline-toolbar'}
      className="flex h-11 items-center gap-2 border-b border-border bg-surface-primary px-3"
    >
      <div className="flex items-center gap-1">
        <TBtn
          label={t('pipeline.toolbar.undo', { defaultValue: 'Undo' })}
          testId="pipeline-undo"
          icon={<Undo2 size={14} aria-hidden="true" />}
          onClick={undo}
          disabled={!canUndo}
        />
        <TBtn
          label={t('pipeline.toolbar.redo', { defaultValue: 'Redo' })}
          testId="pipeline-redo"
          icon={<Redo2 size={14} aria-hidden="true" />}
          onClick={redo}
          disabled={!canRedo}
        />
      </div>

      <span className="h-6 w-px bg-border" aria-hidden="true" />

      <TBtn
        label={t('pipeline.toolbar.fit', { defaultValue: 'Fit view' })}
        testId="pipeline-fit"
        icon={<Maximize2 size={14} aria-hidden="true" />}
        onClick={onFitView}
      />
      <TBtn
        label={t('pipeline.toolbar.explain', {
          defaultValue: 'Explain this pipeline',
        })}
        testId="pipeline-explain"
        icon={<Sparkles size={14} aria-hidden="true" />}
        onClick={onExplain}
      />
      <ModuleGuideButton content={pipelinesGuide} />

      {onOpenLibrary && (
        <TBtn
          label={t('pipeline.toolbar.open', { defaultValue: 'Open' })}
          title={t('pipeline.toolbar.open_hint', {
            defaultValue: 'Open a saved workflow or start from a template',
          })}
          testId="pipeline-open-library"
          icon={<FolderOpen size={14} aria-hidden="true" />}
          onClick={onOpenLibrary}
        />
      )}

      {issueCount > 0 && (
        <span
          data-testid="pipeline-issue-chip"
          className="ms-1 inline-flex items-center gap-1 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-2 py-1 text-xs font-medium text-semantic-warning"
        >
          {t('pipeline.toolbar.issues', {
            defaultValue: '{{count}} issue(s)',
            count: issueCount,
          })}
        </span>
      )}

      <span className="ms-auto h-6 w-px bg-border" aria-hidden="true" />

      {dirty && (
        <span
          data-testid="pipeline-dirty-badge"
          className="inline-flex items-center gap-1.5 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg px-2 py-1 text-xs font-medium text-semantic-warning"
          title={t('pipeline.toolbar.unsaved_hint', {
            defaultValue: 'You have unsaved changes. Press Save to keep them.',
          })}
        >
          <span
            className="h-1.5 w-1.5 rounded-full bg-semantic-warning"
            aria-hidden="true"
          />
          {t('pipeline.toolbar.unsaved', { defaultValue: 'Unsaved changes' })}
        </span>
      )}

      <TBtn
        label={t('pipeline.toolbar.save', { defaultValue: 'Save' })}
        testId="pipeline-save"
        icon={<Save size={14} aria-hidden="true" />}
        onClick={onSave}
        disabled={busy}
      />
      {running ? (
        <TBtn
          label={t('pipeline.toolbar.detach', { defaultValue: 'Detach' })}
          title={t('pipeline.toolbar.detach_hint', {
            defaultValue:
              'Hide this run from the canvas. The run keeps going in the background.',
          })}
          testId="pipeline-stop"
          icon={<EyeOff size={14} aria-hidden="true" />}
          onClick={onStop}
          variant="default"
        />
      ) : (
        <TBtn
          label={t('pipeline.toolbar.run', { defaultValue: 'Run' })}
          testId="pipeline-run"
          icon={<Play size={14} aria-hidden="true" />}
          onClick={onRun}
          disabled={busy}
          variant="primary"
        />
      )}
    </div>
  );
}

export default PipelineToolbar;
