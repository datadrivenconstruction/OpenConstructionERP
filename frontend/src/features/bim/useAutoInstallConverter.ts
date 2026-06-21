/**
 * useAutoInstallConverter — fire-and-forget background install of the DDC
 * converter a just-uploaded CAD/BIM file needs, with NO extra click.
 *
 * Goal (2026-06): the user used to have to find and press an "Install"
 * button in BIMConverterStatusBanner / InstallConverterPrompt before any
 * converter would download. Now, the moment a convertible file is picked
 * (.rvt / .rfa / .ifc / .dwg / .dxf / .dgn) and the matching converter is
 * not yet on disk, the install starts automatically in the background and
 * the existing progress UI (ConverterInstallProgressBar) is surfaced
 * inline by the caller. The manual Install / Retry buttons stay as a
 * fallback only.
 *
 * It reuses the existing, unchanged install contract:
 *   - installBIMConverter(converterId)   — kicks off + polls to terminal
 *   - fetchBIMConverters()               — converter list (size_mb, installed)
 *
 * Safety rules implemented here (per spec):
 *   1. Single-flight: never start a second install for the same converter
 *      while one is already running (guarded by ``_autoInstallRunning``,
 *      a module-level Set that survives component remounts).
 *   2. Idempotent per session: never auto-trigger more than once per
 *      converter per browser session UNLESS the previous attempt ended in
 *      error (guarded by ``_autoInstallAttempted``; cleared on error).
 *   3. Never auto-trigger when the converter is already installed, already
 *      running, or when the upload itself is still resolving the id.
 *   4. The install never blocks the upload — it runs in parallel.
 */

import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  fetchBIMConverters,
  installBIMConverter,
  type BIMConvertersResponse,
} from './api';

/* ── Extension → converter id mapping ──────────────────────────────────── */

/** Canonical DDC converter ids. ``dwg`` also covers .dxf, ``rvt`` also
 *  covers .rfa, ``ifc`` also covers .ifczip. Mirrors the backend's alias
 *  handling so a dropped .rfa correctly resolves to the rvt converter. */
const EXT_TO_CONVERTER_ID: Record<string, string> = {
  rvt: 'rvt',
  rfa: 'rvt',
  ifc: 'ifc',
  ifczip: 'ifc',
  dwg: 'dwg',
  dxf: 'dwg',
  dgn: 'dgn',
};

/** Converter ids that have a built-in backend fallback parser, so the
 *  model still opens (approximately) while the real binary downloads.
 *  Kept in sync with CONVERTERS_WITH_FALLBACK in BIMConverterStatusBanner. */
const CONVERTERS_WITH_FALLBACK = new Set<string>(['ifc']);

/**
 * Resolve a filename to the DDC converter id that can process it, or null
 * when the extension needs no dedicated converter (.csv/.xlsx/.fbx/.obj…).
 */
export function converterIdForFile(filename: string | null | undefined): string | null {
  if (!filename) return null;
  const dot = filename.lastIndexOf('.');
  if (dot < 0) return null;
  const ext = filename.slice(dot + 1).toLowerCase();
  return EXT_TO_CONVERTER_ID[ext] ?? null;
}

/* ── Session-scoped single-flight + once-per-session guards ─────────────── */

/** Converter ids with an auto-install currently in flight. Module scope so
 *  two components (e.g. the upload panel and the status banner) can never
 *  both kick off the same download. */
const _autoInstallRunning = new Set<string>();

/** Converter ids we have already auto-attempted at least once this session.
 *  Prevents a second automatic trigger for the same converter. Cleared for
 *  a converter when its attempt ends in error, so a later upload (or the
 *  manual Retry fallback) can try again. */
const _autoInstallAttempted = new Set<string>();

export interface AutoInstallConverterState {
  /** True while the background install for this converter is in flight. */
  installing: boolean;
  /** The converter id being auto-installed (echo of the resolved input). */
  converterId: string | null;
  /** Expected download size in MB (from converter metadata), 0 if unknown. */
  sizeMb: number;
  /** True once an auto-install attempt has FAILED — only then should the
   *  caller surface the manual-install fallback guidance. */
  errored: boolean;
  /** True when this converter has a built-in fallback parser (IFC), so the
   *  model still opens while the binary downloads. */
  hasFallback: boolean;
  /** Manual fallback: retry the install (clears the errored/attempted state
   *  first). Safe to wire to a "Retry" button. */
  retry: () => void;
}

/**
 * Auto-install the converter for ``converterId`` once it is known to be
 * missing. Pass ``enabled=false`` (e.g. while the file/converter id is
 * still resolving, or the upload context isn't ready) to suppress the
 * trigger entirely.
 *
 * The hook is a no-op when:
 *   - converterId is null,
 *   - the converter is already installed,
 *   - an install is already running for it (anywhere in the app),
 *   - it was already auto-attempted this session and did not error.
 */
export function useAutoInstallConverter(
  converterId: string | null,
  enabled = true,
): AutoInstallConverterState {
  const queryClient = useQueryClient();
  const [errored, setErrored] = useState(false);
  // Tracks the converter this hook instance currently "owns" an in-flight
  // install for, so onSettled can release the module-level single-flight
  // lock for the right id even if the prop changed meanwhile.
  const owningRef = useRef<string | null>(null);

  // Reuse the shared converter-status cache so size_mb / installed match the
  // banner and the install prompt exactly.
  const { data } = useQuery<BIMConvertersResponse>({
    queryKey: ['bim-converters'],
    queryFn: () => fetchBIMConverters(),
    staleTime: 30_000,
    enabled: enabled && Boolean(converterId),
  });

  const converter = converterId
    ? data?.converters.find((c) => c.id === converterId)
    : undefined;
  const sizeMb = converter?.size_mb ?? 0;
  const hasFallback = converterId ? CONVERTERS_WITH_FALLBACK.has(converterId) : false;

  const installMutation = useMutation({
    mutationFn: (id: string) => installBIMConverter(id),
    onSuccess: (result, id) => {
      // installBIMConverter resolves only at a terminal stage. ``installed``
      // false here means a real failure (smoke test failed) or a platform
      // that can't auto-install (Linux/macOS apt path) - in both cases the
      // automatic path is exhausted, so reveal the manual fallback and let
      // the converter be auto-attempted again next time.
      if (result.installed) {
        setErrored(false);
      } else {
        setErrored(true);
        _autoInstallAttempted.delete(id);
      }
      queryClient.invalidateQueries({ queryKey: ['bim-converters'] });
      queryClient.invalidateQueries({ queryKey: ['takeoff', 'converters'] });
      queryClient.invalidateQueries({ queryKey: ['dwg-offline-readiness'] });
      queryClient.invalidateQueries({ queryKey: ['bim-converters-version-check'] });
    },
    onError: (_err, id) => {
      setErrored(true);
      // Allow a future automatic retry after a hard failure.
      _autoInstallAttempted.delete(id);
    },
    onSettled: () => {
      const owned = owningRef.current;
      if (owned) {
        _autoInstallRunning.delete(owned);
        owningRef.current = null;
      }
    },
  });

  const isPending = installMutation.isPending;

  useEffect(() => {
    if (!enabled) return;
    if (!converterId) return;
    // Wait until the status query has resolved so we don't fire against
    // unknown install state.
    if (!data) return;
    if (!converter) return;
    if (converter.installed) return;
    // Single-flight + once-per-session guards.
    if (_autoInstallRunning.has(converterId)) return;
    if (_autoInstallAttempted.has(converterId)) return;
    if (isPending) return;

    _autoInstallAttempted.add(converterId);
    _autoInstallRunning.add(converterId);
    owningRef.current = converterId;
    setErrored(false);
    installMutation.mutate(converterId);
    // installMutation identity is stable across renders for our purposes;
    // depending on the resolved primitives keeps the effect honest.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, converterId, data, converter?.installed, isPending]);

  const retry = (): void => {
    if (!converterId) return;
    if (_autoInstallRunning.has(converterId)) return;
    setErrored(false);
    _autoInstallAttempted.add(converterId);
    _autoInstallRunning.add(converterId);
    owningRef.current = converterId;
    installMutation.mutate(converterId);
  };

  return {
    installing: isPending,
    converterId,
    sizeMb,
    errored,
    hasFallback,
    retry,
  };
}

export default useAutoInstallConverter;
