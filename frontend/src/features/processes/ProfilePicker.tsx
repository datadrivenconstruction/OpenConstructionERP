// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Ready-made profiles for the background services: fastest start, balanced,
 * or everything on. Each card says what it costs in memory; the active one is
 * found by comparing the services that are on with what each profile would run.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { AlertTriangle, Check, Feather, Lock, Scale, Sparkles, type LucideIcon } from 'lucide-react';

import { formatMb } from './labels';
import type { ProcessInfo, ProcessPreset } from './api';

/** The memory floor the core is sized for (docs/INSTALL_LINUX.md). */
export const SERVER_BUDGET_MB = 3072;

/** Services a profile would leave on. Locked ones keep their current state. */
export function presetSet(processes: ProcessInfo[], preset: ProcessPreset): Set<string> {
  const on = new Set<string>();
  for (const p of processes) {
    let want: boolean;
    if (p.env_locked) want = p.enabled;
    else if (preset === 'all') want = true;
    else if (preset === 'recommended') want = p.default_enabled || p.required;
    else want = p.required;
    if (want) on.add(p.id);
  }
  return on;
}

export function presetRamMb(processes: ProcessInfo[], preset: ProcessPreset): number {
  const on = presetSet(processes, preset);
  return processes.filter((p) => on.has(p.id)).reduce((sum, p) => sum + p.ram_mb_estimate, 0);
}

/** The profile whose service set equals the current one, or null for a hand-made mix. */
export function activePreset(processes: ProcessInfo[]): ProcessPreset | null {
  if (processes.length === 0) return null;
  const current = processes
    .filter((p) => p.enabled)
    .map((p) => p.id)
    .sort()
    .join('|');
  for (const preset of ['recommended', 'minimal', 'all'] as ProcessPreset[]) {
    if ([...presetSet(processes, preset)].sort().join('|') === current) return preset;
  }
  return null;
}

const CARDS: { preset: ProcessPreset; icon: LucideIcon; key: string; name: string; promise: string }[] = [
  {
    preset: 'minimal',
    icon: Feather,
    key: 'speed',
    name: 'Maximum speed',
    promise: 'Fastest start, least memory. AI search and background sync stay off until you need them.',
  },
  {
    preset: 'recommended',
    icon: Scale,
    key: 'balanced',
    name: 'Balanced',
    promise: 'What most teams need: search and the usual helpers on, heavy extras off.',
  },
  {
    preset: 'all',
    icon: Sparkles,
    key: 'features',
    name: 'Maximum features',
    promise: 'Every service on, so nothing waits to start. Needs a roomy server.',
  },
];

interface Props {
  processes: ProcessInfo[];
  isAdmin: boolean;
  pending: boolean;
  onApply: (preset: ProcessPreset) => void;
}

export function ProfilePicker({ processes, isAdmin, pending, onApply }: Props) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState<ProcessPreset | null>(null);
  const active = activePreset(processes);
  const locked = processes.filter((p) => p.env_locked).length;

  const choose = (preset: ProcessPreset) => {
    if (preset === active) return;
    if (preset === 'all' && presetRamMb(processes, 'all') > SERVER_BUDGET_MB) {
      setConfirming('all');
      return;
    }
    setConfirming(null);
    onApply(preset);
  };

  return (
    <section
      aria-label={t('processes.profile_title', { defaultValue: 'Choose a profile' })}
      className="mt-3"
      data-testid="processes-profiles"
    >
      <h3 className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
        {t('processes.profile_title', { defaultValue: 'Choose a profile' })}
      </h3>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {CARDS.map(({ preset, icon: Icon, key, name, promise }) => {
          const ram = presetRamMb(processes, preset);
          const count = presetSet(processes, preset).size;
          const isActive = active === preset;
          const overBudget = confirming === preset;
          return (
            <div
              key={preset}
              data-testid={`processes-profile-${preset}`}
              data-active={isActive ? 'true' : 'false'}
              className={clsx(
                'flex min-w-0 flex-col rounded-xl border p-2.5 text-xs',
                isActive ? 'border-oe-blue bg-oe-blue/5' : 'border-border-light bg-surface-elevated',
              )}
            >
              <div className="flex items-center gap-1.5">
                <Icon size={14} className="shrink-0 text-oe-blue" aria-hidden />
                <span className="font-semibold text-content-primary">
                  {t(`processes.profile_${key}_name`, { defaultValue: name })}
                </span>
              </div>
              {preset === 'recommended' && (
                <span className="mt-1 w-fit rounded-full bg-oe-blue/10 px-1.5 py-0.5 text-2xs font-medium text-oe-blue">
                  {t('processes.profile_recommended', { defaultValue: 'Recommended' })}
                </span>
              )}
              <p className="mt-1 flex-1 text-content-secondary">
                {t(`processes.profile_${key}_promise`, { defaultValue: promise })}
              </p>
              <p className="mt-1.5 tabular-nums text-content-tertiary">
                {t('processes.profile_summary', {
                  defaultValue: 'About {{ram}} of memory, {{services}} services on',
                  ram: formatMb(t, ram),
                  services: count,
                })}
              </p>
              {overBudget ? (
                <div role="alert" className="mt-2 rounded-lg bg-amber-500/10 p-2 text-amber-800 dark:text-amber-200">
                  <p className="flex items-start gap-1">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" aria-hidden />
                    {t('processes.profile_confirm', {
                      defaultValue: 'This needs about {{ram}} and may slow a small server. Turn everything on?',
                      ram: formatMb(t, ram),
                    })}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => {
                        setConfirming(null);
                        onApply('all');
                      }}
                      data-testid="processes-profile-confirm"
                      className="rounded-md bg-amber-600 px-2 py-1 font-medium text-white disabled:opacity-50"
                    >
                      {t('processes.profile_confirm_yes', { defaultValue: 'Turn all on' })}
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(null)}
                      data-testid="processes-profile-cancel"
                      className="rounded-md border border-border-light px-2 py-1 font-medium text-content-primary"
                    >
                      {t('processes.profile_confirm_no', { defaultValue: 'Cancel' })}
                    </button>
                  </div>
                </div>
              ) : isActive ? (
                <span className="mt-2 inline-flex items-center gap-1 font-medium text-oe-blue">
                  <Check size={12} aria-hidden />
                  {t('processes.profile_active', { defaultValue: 'Active' })}
                </span>
              ) : isAdmin ? (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => choose(preset)}
                  data-testid={`processes-profile-choose-${preset}`}
                  className="mt-2 rounded-lg border border-border-light px-2 py-1 font-medium text-content-primary hover:bg-surface-secondary disabled:opacity-50"
                >
                  {t('processes.profile_choose', { defaultValue: 'Use this profile' })}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>
      {active === null && (
        <p className="mt-2 text-xs text-content-secondary" data-testid="processes-profile-custom">
          <span className="font-semibold">{t('processes.profile_custom', { defaultValue: 'Custom' })}</span>
          {': '}
          {t('processes.profile_custom_hint', { defaultValue: 'You changed services by hand.' })}
        </p>
      )}
      {locked > 0 && (
        <p className="mt-1 flex items-center gap-1 text-2xs text-content-tertiary" data-testid="processes-profile-locked">
          <Lock size={10} aria-hidden />
          {t('processes.profile_locked', {
            defaultValue: 'Locked by the server settings, a profile does not change them: {{services}}',
            services: locked,
          })}
        </p>
      )}
    </section>
  );
}
