// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Simple / Advanced mode a user gets before they pick one.
//
// Simple used to be the default for everybody, and for a profile without a
// workspace Simple hides whole groups (changes, finance, procurement,
// scheduling, field work, quality) that the profile the user picked may well
// have switched on. The company profile already says what the company does,
// and `module_preferences` already trims the menu to it, so the default now
// follows the profile:
//
//   - a profile with a workspace (`workspaces.ts`) -> Simple, which for that
//     profile IS the workspace, with every other screen one click away;
//   - a profile without one -> Advanced, so the modules the profile enabled
//     are all in the menu rather than hidden a second time;
//   - no profile -> Simple, as before.
//
// Only a default: a mode the user picked (server or this browser) wins, and
// the store's `applyDefault` writes nothing, so the default never turns into
// a stored "choice".

import { useEffect } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  hydrateViewModeFromServer,
  useViewModeStore,
  type ViewMode,
} from '@/stores/useViewModeStore';
import { useCompanyPresetKey } from './useCompanyWorkspace';
import { workspaceFor } from './workspaces';

/** The default mode for a company preset key (null = no profile chosen). */
export function defaultViewModeFor(presetKey: string | null): ViewMode {
  if (!presetKey) return 'simple';
  return workspaceFor(presetKey) ? 'simple' : 'advanced';
}

/** Load the user's stored choice and, while there is none, show the default. */
export function useViewModeDefault(): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const userId = useAuthStore((s) => s.userId) ?? null;
  const presetKey = useCompanyPresetKey();
  const chosen = useViewModeStore((s) => s.chosen);
  const applyDefault = useViewModeStore((s) => s.applyDefault);

  useEffect(() => {
    void hydrateViewModeFromServer(isAuthenticated ? userId : null);
  }, [isAuthenticated, userId]);

  useEffect(() => {
    if (!isAuthenticated || chosen) return;
    applyDefault(defaultViewModeFor(presetKey));
  }, [isAuthenticated, chosen, presetKey, applyDefault]);
}
