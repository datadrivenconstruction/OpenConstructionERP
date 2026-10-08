// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * On a fresh install the demo projects are installed in the background right
 * after the server is up, so the first look at the project list can be empty.
 * This says so while that is happening, instead of inviting a first project.
 */

import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { isLoading, useProcesses } from './api';

export function DemoSeedingHint() {
  const { t } = useTranslation();
  const { data } = useProcesses();
  const seed = data?.processes.find((p) => p.id === 'demo_data_seed');
  if (!seed || !(seed.status === 'running' || isLoading(seed))) return null;
  return (
    <div
      role="status"
      data-testid="demo-seeding-hint"
      className="mb-3 flex items-center gap-2 rounded-xl border border-sky-500/25 bg-sky-500/5 px-3 py-2 text-xs text-content-secondary"
    >
      <Loader2 size={14} className="shrink-0 animate-spin text-sky-600" aria-hidden />
      {t('processes.demo_seeding', {
        defaultValue: 'The demo projects are still being installed. They appear here in about a minute.',
      })}
    </div>
  );
}
