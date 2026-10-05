// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The locked explanation in the size of a panel, drawn by TrainerPanelGate in
// place of a panel the course has not opened yet (first use: the BOQ markups
// panel). Same content as LockedModulePage, compact.
//
// The card takes over the panel's DOM id, so anything that scrolls to the
// panel (the BOQ toolbar "Markups" button, an Academy deep link with
// `#boq-markups-panel`) lands on the card instead of nowhere.

import { LockedLockContent, type TrainerLockMode } from './LockedModulePage';

export interface LockedPanelCardProps {
  lockId: string;
  /** DOM id of the panel this card stands in for. */
  anchorId?: string | null;
  /** The gate's `useTrainerMode()` result; see `TrainerLockMode`. */
  mode: TrainerLockMode;
}

export function LockedPanelCard({ lockId, anchorId, mode }: LockedPanelCardProps) {
  return (
    <div id={anchorId ?? undefined} className="mt-4 scroll-mt-28" data-testid="trainer-locked-panel">
      <LockedLockContent lockId={lockId} variant="panel" mode={mode} />
    </div>
  );
}
