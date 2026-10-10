// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Which company profile the signed-in user chose, and the workspace it brings.
//
// The server is the source: `GET /v1/users/me/onboarding/` returns the
// `company_type` the wizard or the Modules page last saved, so the answer
// survives a reload and follows the user to another browser. `oe_company_type`
// in localStorage is only the instant cache for the first paint and for a
// server that cannot be reached; once the server answers, its answer wins and
// is written back to the cache (an empty answer clears it), so the Modules
// page (which reads the cache) opens on the right profile in a browser the
// wizard never ran in.
//
// The query entry is shared with the dashboard's first-run check, which reads
// `completed` from the same response, and it is one entry per user
// (`meOnboardingQuery.ts`). Whoever saves a profile writes the response into
// it, so the sidebar follows the switch without waiting out the stale time.

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { useMeOnboardingQueryKey } from './meOnboardingQuery';
import { usePartnerPack } from '@/shared/hooks/usePartnerPack';
import { effectiveCompanyPresetKey, workspaceFor, type Workspace } from './workspaces';

/** localStorage cache of the chosen profile key. Written by the wizard and the
 *  Modules page profile switch, read by the Modules page. */
export const COMPANY_TYPE_STORAGE_KEY = 'oe_company_type';

/** The part of `OnboardingResponse` the client reads. */
export interface MeOnboarding {
  completed: boolean;
  company_type?: string | null;
  company_size?: string | null;
}

function readCachedCompanyType(): string | null {
  try {
    return localStorage.getItem(COMPANY_TYPE_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** The company preset key the signed-in user's menu follows: their own
 *  choice, else the active pack's default profile, else null. */
export function useCompanyPresetKey(): string | null {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const queryKey = useMeOnboardingQueryKey();
  const { data } = useQuery({
    queryKey,
    queryFn: () => apiGet<MeOnboarding>('/v1/users/me/onboarding/').catch(() => null),
    enabled: isAuthenticated,
    retry: false,
    staleTime: 5 * 60_000,
    // The menu mounts once per sign-in, so asking again on mount costs one
    // request per session and picks up a profile saved in another browser
    // since this one last asked.
    refetchOnMount: 'always',
  });

  // `data` is undefined while loading and null when the server could not be
  // asked; both fall back to the cache. An answer, even an empty one, wins.
  const serverKey = data ? (data.company_type ?? null) : undefined;

  useEffect(() => {
    if (serverKey === undefined) return;
    try {
      // No profile on the server: the cache is left over from another user on
      // this browser, or from a save that never reached the server. Either way
      // it is not this user's answer, and kept it would open every reload on
      // that workspace until the server replies.
      if (serverKey === null) {
        localStorage.removeItem(COMPANY_TYPE_STORAGE_KEY);
      } else if (localStorage.getItem(COMPANY_TYPE_STORAGE_KEY) !== serverKey) {
        localStorage.setItem(COMPANY_TYPE_STORAGE_KEY, serverKey);
      }
    } catch {
      // Storage unavailable: the server answer still drives this render.
    }
  }, [serverKey]);

  // A user who has chosen no profile gets the one the installation's pack
  // names, if it names one. Nothing is stored for them, here or on the server,
  // so the cache above stays this user's own answer and their first real
  // choice wins from then on. This is how one pack install reaches the people
  // who never open the setup wizard.
  const { data: pack } = usePartnerPack();
  const packDefault = pack?.active ? (pack.manifest?.default_company_profile ?? null) : null;

  const ownKey = serverKey !== undefined ? serverKey : readCachedCompanyType();
  return effectiveCompanyPresetKey(ownKey, packDefault);
}

/** The workspace the user's company profile brings, or null when it has none. */
export function useCompanyWorkspace(): Workspace | null {
  return workspaceFor(useCompanyPresetKey());
}
