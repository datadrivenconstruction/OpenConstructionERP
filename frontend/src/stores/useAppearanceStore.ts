// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The UI appearance in effect: the user's own choice layered over the
 * workspace default an admin set. See `shared/lib/appearance.ts` for the axes
 * and the boot script in index.html for the first paint.
 *
 * `user` is null when the user follows the workspace. Picking anything makes a
 * full personal override; "Use workspace default" clears it again.
 */
import { create } from 'zustand';
import {
  type Appearance,
  type AppearanceAxis,
  USER_APPEARANCE_KEY,
  WORKSPACE_APPEARANCE_KEY,
  applyAppearance,
  readStoredAppearance,
  resolveAppearance,
  sanitizeAppearance,
  writeStoredAppearance,
} from '@/shared/lib/appearance';

interface AppearanceState {
  /** Personal override, or null to follow the workspace default. */
  user: Partial<Appearance> | null;
  /** Workspace default from the server (cached locally), or null. */
  workspace: Partial<Appearance> | null;
  /** What is applied right now. */
  effective: Appearance;
  /** Replace the personal choice with a whole style. */
  setAppearance: (value: Appearance) => void;
  /** Change one axis; the rest keep their current effective value. */
  setAxis: <K extends AppearanceAxis>(axis: K, value: Appearance[K]) => void;
  /** Drop the personal override and follow the workspace default again. */
  followWorkspace: () => void;
  /** Take the workspace default from the branding payload (unvalidated input). */
  setWorkspaceDefault: (raw: unknown) => void;
}

function commit(user: Partial<Appearance> | null, workspace: Partial<Appearance> | null) {
  const effective = resolveAppearance(user, workspace);
  if (typeof document !== 'undefined') applyAppearance(effective);
  return { user, workspace, effective };
}

export const useAppearanceStore = create<AppearanceState>((set, get) => {
  const user = readStoredAppearance(USER_APPEARANCE_KEY);
  const workspace = readStoredAppearance(WORKSPACE_APPEARANCE_KEY);

  if (typeof window !== 'undefined') {
    // Another tab changed the choice: follow it without a reload.
    window.addEventListener('storage', (e) => {
      if (e.key !== USER_APPEARANCE_KEY && e.key !== WORKSPACE_APPEARANCE_KEY) return;
      set(
        commit(readStoredAppearance(USER_APPEARANCE_KEY), readStoredAppearance(WORKSPACE_APPEARANCE_KEY)),
      );
    });
  }

  return {
    user,
    workspace,
    effective: resolveAppearance(user, workspace),

    setAppearance: (value) => {
      const next = sanitizeAppearance(value);
      writeStoredAppearance(USER_APPEARANCE_KEY, next);
      set(commit(next, get().workspace));
    },

    setAxis: (axis, value) => {
      get().setAppearance({ ...get().effective, [axis]: value });
    },

    followWorkspace: () => {
      writeStoredAppearance(USER_APPEARANCE_KEY, null);
      set(commit(null, get().workspace));
    },

    setWorkspaceDefault: (raw) => {
      const next = sanitizeAppearance(raw);
      writeStoredAppearance(WORKSPACE_APPEARANCE_KEY, next);
      set(commit(get().user, next));
    },
  };
});
