// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The assistant's suggestion of an app action (`propose_ui_action`): what it
 * would do, how sure the assistant is, and Run / Dismiss. Nothing happens
 * until the person clicks Run. An id this browser does not know is shown as
 * unavailable rather than guessed at.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Play, X, Zap } from 'lucide-react';
import { ConfidenceBadge } from '@/shared/ui/ConfidenceBadge';
import { getAction, useActions } from '@/shared/lib/actions/registry';
import { useActionRunner, useBindings } from '@/shared/lib/actions/useActionRunner';
import { formatShortcut } from '@/shared/lib/actions/shortcuts';
import { ActionButton } from './ActionControls';
import './actions.css';

export interface UiActionData {
  action_id: string;
  confidence: number;
  reason?: string;
}

export function isUiActionData(data: unknown): data is UiActionData {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  return typeof d.action_id === 'string' && typeof d.confidence === 'number';
}

export function UiActionCard({ data }: { data: unknown }) {
  const { t } = useTranslation();
  useActions(); // re-render when modules register late
  const run = useActionRunner();
  const bindings = useBindings();
  const [state, setState] = useState<'proposed' | 'ran' | 'dismissed'>('proposed');

  if (!isUiActionData(data)) return null;
  const action = getAction(data.action_id);
  const title = action ? t(action.titleKey, { defaultValue: action.defaultTitle }) : data.action_id;
  const shortcut = action ? bindings.get(action.id) : undefined;
  const Icon = action?.icon ?? Zap;

  return (
    <div
      className="oe-act rounded-lg border border-[var(--act-border)] bg-[var(--act-bg)] p-3 text-sm"
      data-testid="ui-action-card"
    >
      <div className="flex items-start gap-2">
        <Icon size={16} className="mt-0.5 shrink-0 text-[var(--act-accent)]" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-2xs font-semibold uppercase tracking-wider text-[var(--act-text-2)]">
            {t('chat.ui_action.heading', { defaultValue: 'Suggested action' })}
          </div>
          <div className="truncate font-medium text-[var(--act-text)]">{title}</div>
          {data.reason && <div className="mt-0.5 text-xs text-[var(--act-text-2)]">{data.reason}</div>}
        </div>
        <ConfidenceBadge score={data.confidence} showScore />
      </div>
      {!action ? (
        <p className="mt-2 text-xs text-[var(--act-text-2)]">
          {t('chat.ui_action.unavailable', { defaultValue: 'This action is not available here.' })}
        </p>
      ) : state === 'proposed' ? (
        <div className="mt-2 flex items-center gap-2">
          <ActionButton
            tone="primary"
            icon={<Play size={12} />}
            onClick={() => {
              run(action);
              setState('ran');
            }}
          >
            {t('chat.ui_action.run', { defaultValue: 'Run' })}
          </ActionButton>
          <ActionButton tone="ghost" icon={<X size={12} />} onClick={() => setState('dismissed')}>
            {t('chat.ui_action.dismiss', { defaultValue: 'Dismiss' })}
          </ActionButton>
          {shortcut && (
            <kbd className="ms-auto font-mono text-2xs text-[var(--act-text-2)]">{formatShortcut(shortcut)}</kbd>
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs text-[var(--act-text-2)]">
          {state === 'ran'
            ? t('chat.ui_action.done', { defaultValue: 'Done.' })
            : t('chat.ui_action.dismissed', { defaultValue: 'Dismissed.' })}
        </p>
      )}
    </div>
  );
}

export default UiActionCard;
