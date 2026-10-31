// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One flag: the server has refused a write because this deployment is the
 * public demonstration.
 *
 * The refusal is recognised in `shared/lib/api.ts` and shown by
 * `shared/ui/DemoReadOnlyDialog.tsx`. This store is the seam between them, in
 * the same shape the transport already uses for the rate-limit toast: the
 * transport sets state on a zustand store and still throws, so nothing about
 * how a caller handles its own error changes.
 *
 * It carries a boolean and nothing else, deliberately.
 *
 * The refusal body also carries a plain English `message`, a fallback for
 * callers that are not this app. The screen shows its own translated text, so
 * that sentence must never reach a reader. Keeping it out of this store is how
 * that is enforced rather than merely intended: there is nothing here to
 * render, so no later edit can render it by accident.
 */
import { create } from 'zustand';

interface DemoReadOnlyStore {
  /** True while the explanation is on screen. */
  open: boolean;
  /**
   * Report a refused write.
   *
   * Idempotent while the dialog is already up. One click on a screen with
   * several pending writes produces several refusals in the same instant, and
   * they are all one event to the person who clicked. Raising again would
   * re-run the dialog's mount effects - including the refetch that puts the
   * screen back to what the server holds - for no gain.
   *
   * Not once-per-session, though. A visitor who dismisses the dialog and then
   * tries to change something else is asking the same question again and is
   * owed the same answer.
   */
  raise: () => void;
  dismiss: () => void;
}

export const useDemoReadOnlyStore = create<DemoReadOnlyStore>((set, get) => ({
  open: false,

  raise: () => {
    if (get().open) return;
    set({ open: true });
  },

  dismiss: () => set({ open: false }),
}));

let readOnlyDeployment = false;

/** Whether this deployment is the read-only demo, as reported by /system/status or a refusal. */
export function isDemoReadOnly(): boolean {
  return readOnlyDeployment;
}

/** Record that the deployment refuses writes, so background writes can stay quiet. */
export function markDemoReadOnly(value = true): void {
  readOnlyDeployment = value;
}
