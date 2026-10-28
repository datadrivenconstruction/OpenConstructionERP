// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Trigger panel for the custom-agent builder (Item 29).
//
// Lets a user subscribe an agent to platform events so it runs automatically
// when one fires (e.g. when an RFI is created). An event-fired run is a normal
// run and never auto-applies its output. Triggers whose source event is not yet
// wired are shown disabled with a "coming soon" hint, so the picker never
// implies an action that does not happen.
import { useTranslation } from 'react-i18next';
import { Zap } from 'lucide-react';
import clsx from 'clsx';

import type { EventTriggerDescriptor } from '../api';

interface TriggerPanelProps {
  /** The full event-trigger catalogue (with availability) from the API. */
  triggers: EventTriggerDescriptor[];
  /** Currently-subscribed trigger slugs. */
  selected: string[];
  loading?: boolean;
  onChange: (next: string[]) => void;
}

export function TriggerPanel({
  triggers,
  selected,
  loading = false,
  onChange,
}: TriggerPanelProps): JSX.Element {
  const { t } = useTranslation();

  if (loading) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('agents.triggers.loading', { defaultValue: 'Loading events…' })}
      </p>
    );
  }

  if (triggers.length === 0) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('agents.triggers.none', { defaultValue: 'No event triggers are available yet.' })}
      </p>
    );
  }

  const toggle = (name: string) => {
    if (selected.includes(name)) onChange(selected.filter((s) => s !== name));
    else onChange([...selected, name]);
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-content-secondary">
        {t('agents.triggers.intro', {
          defaultValue: 'Run this agent automatically when something happens in the platform.',
        })}
      </p>
      <ul className="space-y-1.5">
        {triggers.map((trig) => {
          const checked = selected.includes(trig.name);
          const disabled = !trig.available;
          return (
            <li key={trig.name}>
              <label
                className={clsx(
                  'flex items-start gap-2.5 rounded-lg border p-2.5 transition-colors',
                  disabled
                    ? 'cursor-not-allowed border-border-light bg-surface-secondary/30 opacity-60'
                    : 'cursor-pointer border-border-light bg-surface-secondary/40 hover:border-oe-blue/40',
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(trig.name)}
                  className="mt-0.5 h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
                    <Zap className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                    {t(`agents.triggers.${trig.name}.label`, { defaultValue: trig.label })}
                    {disabled && (
                      <span className="rounded-full bg-surface-tertiary px-1.5 py-0.5 text-2xs font-medium text-content-tertiary">
                        {t('agents.triggers.coming_soon', { defaultValue: 'Coming soon' })}
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-content-tertiary">
                    {t(`agents.triggers.${trig.name}.description`, { defaultValue: trig.description })}
                  </span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      <div className="rounded-md bg-semantic-info-bg/60 px-2.5 py-1.5 text-2xs text-content-secondary">
        {t('agents.triggers.review_note', {
          defaultValue:
            'Event-triggered runs are saved like any run for you to review - nothing is applied automatically.',
        })}
      </div>
    </div>
  );
}

export default TriggerPanel;
