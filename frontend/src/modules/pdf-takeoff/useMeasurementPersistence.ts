import { useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { QueryClientContext } from '@tanstack/react-query';
import { takeoffApi, type MeasurementCreate, type MeasurementResponse } from '@/features/takeoff/api';
import type { MeasurementDocumentSource } from '@/features/takeoff/takeoffRoutes';
import {
  type PageScales,
  hydratePageScales,
  scaleForPage,
} from './data/page-scales';

/* ── Types (mirrored from TakeoffViewerModule) ──────────────────────── */

interface Point {
  x: number;
  y: number;
}

interface Measurement {
  id: string;
  type: 'distance' | 'polyline' | 'area' | 'volume' | 'count'
    | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight';
  points: Point[];
  value: number;
  unit: string;
  label: string;
  annotation: string;
  page: number;
  group: string;
  depth?: number;
  area?: number;
  text?: string;
  color?: string;
  width?: number;
  height?: number;
  /** Opening deduction (area void). Stored as positive gross area; the
   *  rollup subtracts it. Round-trips so a void survives a server sync. */
  isDeduction?: boolean;
  /** Server-side ID (set after first sync). */
  serverId?: string;
  /** BOQ link metadata carried through persistence. */
  linkedPositionId?: string;
  linkedPositionOrdinal?: string;
  linkedBoqId?: string;
  linkedPositionLabel?: string;
  /** AI-suggested but unconfirmed (issue #194): excluded from server sync
   *  and localStorage until the user accepts it (which clears the flag). */
  suggested?: boolean;
  /** Recognition confidence 0..1 on AI-sourced measurements. */
  confidence?: number;
}

interface ScaleConfig {
  pixelsPerUnit: number;
  unitLabel: string;
}

interface PersistedDocument {
  measurements: Measurement[];
  /** New per-page scale model. Optional so an older document (which only
   *  carried ``scale``) still parses; ``hydratePageScales`` migrates it. */
  pageScales?: PageScales;
  /** Legacy single document-wide scale. Kept for backward-compatible reads
   *  (and still written so a downgrade to an older build keeps working). */
  scale: ScaleConfig;
  savedAt: number;
}

/* ── localStorage helpers (fallback) ─────────────────────────────────── */

const STORAGE_PREFIX = 'oe_takeoff_';
const INDEX_KEY = 'oe_takeoff_index';

function sanitizeKeyPart(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]/g, '_');
}

function docKey(projectId: string | null | undefined, documentId: string): string {
  return `${STORAGE_PREFIX}p_${sanitizeKeyPart(projectId || 'local')}__${sanitizeKeyPart(documentId)}`;
}

function legacyDocKey(fileName: string): string {
  return `${STORAGE_PREFIX}${sanitizeKeyPart(fileName)}`;
}

function loadFromStorage(
  projectId: string | null | undefined,
  documentId: string,
): PersistedDocument | null {
  try {
    const raw = localStorage.getItem(docKey(projectId, documentId));
    if (!raw) return null;
    return JSON.parse(raw) as PersistedDocument;
  } catch {
    return null;
  }
}

function saveToStorage(
  projectId: string | null | undefined,
  documentId: string,
  data: PersistedDocument,
): boolean {
  try {
    const key = docKey(projectId, documentId);
    localStorage.setItem(key, JSON.stringify(data));
    const index = getDocumentIndex();
    if (!index.includes(key)) {
      index.push(key);
      localStorage.setItem(INDEX_KEY, JSON.stringify(index));
    }
    return true;
  } catch {
    // localStorage full — silently fail
    return false;
  }
}

export function removeFromStorage(
  projectId: string | null | undefined,
  documentId: string,
  fileName?: string | null,
): void {
  try {
    const key = docKey(projectId, documentId);
    localStorage.removeItem(key);
    if (fileName) {
      localStorage.removeItem(legacyDocKey(fileName));
    }
    const legacyKey = fileName ? legacyDocKey(fileName) : null;
    const index = getDocumentIndex().filter(
      (n) => n !== key && (!legacyKey || n !== legacyKey),
    );
    localStorage.setItem(INDEX_KEY, JSON.stringify(index));
  } catch {
    // ignore
  }
}

export function getDocumentIndex(): string[] {
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

/* ── Unit canonicalization ───────────────────────────────────────────── */

/**
 * Map the display-glyph unit the viewer emits (`m²` / `m³` via the
 * superscript U+00B2 / U+00B3) to the canonical BOQ unit string
 * (`m2` / `m3`).
 *
 * Even though the backend now accepts the superscript form verbatim
 * (D-TKC-001 backend pairing), cross-module quantity sync — bim_hub
 * `_sync_boq_quantity_from_links`, BOQ linking, the catalogue/cost
 * matchers — keys on the canonical `m`/`m2`/`m3`/`pcs` vocabulary.
 * Persisting the canonical form keeps the server copy aligned with the
 * Export-to-BOQ / link-to-position paths (which already canonicalize),
 * and {@link displayUnit} restores the glyph on round-trip so the UI is
 * unchanged.
 */
function canonicalUnit(unit: string): string {
  switch (unit) {
    case 'm²':
      return 'm2';
    case 'm³':
      return 'm3';
    default:
      return unit || 'm';
  }
}

/** Inverse of {@link canonicalUnit}: restore the superscript display
 *  glyph from the canonical stored unit so a server round-trip renders
 *  identically to a freshly-drawn measurement. */
function displayUnit(unit: string): string {
  switch (unit) {
    case 'm2':
      return 'm²';
    case 'm3':
      return 'm³';
    default:
      return unit;
  }
}

/* ── Convert between frontend Measurement and backend API format ─────── */

function toApiFormat(
  m: Measurement,
  projectId: string,
  documentId: string,
  pageScales?: PageScales,
  documentSource?: MeasurementDocumentSource | null,
): MeasurementCreate {
  // Area measurements carry the polygon area in `m.value`; volume
  // measurements carry the area separately in `m.area`. Persist the
  // canonical dimension fields so bim_hub quantity sync / BOQ linking
  // can pick the right quantity instead of guessing from the unit
  // string alone (D-TKC-031).
  const areaValue =
    m.type === 'area' ? m.value : m.type === 'volume' ? (m.area ?? null) : null;
  // Per-page scale: send the scale of THIS measurement's page, not a single
  // document-wide ratio, so a sheet at 1:500 and a sheet at 1:50 each get
  // their own px-per-unit for the server-side B8 recompute.
  const scale = pageScales ? scaleForPage(pageScales, m.page) : undefined;
  const ppu =
    scale && scale.pixelsPerUnit > 0 ? scale.pixelsPerUnit : null;
  return {
    project_id: projectId,
    document_id: documentId,
    page: m.page,
    type: m.type,
    group_name: m.group || 'General',
    group_color: m.color || '#3B82F6',
    annotation: m.annotation || m.label || null,
    points: m.points,
    measurement_value: m.value || null,
    measurement_unit: canonicalUnit(m.unit),
    depth: m.depth ?? null,
    volume: m.type === 'volume' ? m.value : null,
    perimeter: m.type === 'polyline' ? m.value : null,
    count_value: m.type === 'count' ? Math.round(m.value) : null,
    // Send the calibration so the server-side recompute can verify the
    // client value against the raw geometry (Audit B8) instead of
    // trusting it blindly.
    scale_pixels_per_unit: ppu,
    // Opening deduction only applies to an area; the server enforces this
    // too but we keep the payload honest.
    is_deduction: m.type === 'area' ? Boolean(m.isDeduction) : false,
    linked_boq_position_id: m.linkedPositionId ?? null,
    metadata: {
      text: m.text,
      width: m.width,
      height: m.height,
      area: areaValue ?? undefined,
      frontend_id: m.id,
      linked_boq_id: m.linkedBoqId,
      linked_position_ordinal: m.linkedPositionOrdinal,
      linked_position_label: m.linkedPositionLabel,
      document_source: documentSource ?? undefined,
    },
  };
}

/**
 * Geometry signature for a synced measurement: the set of fields a
 * reshape can change that feed the server-side recompute (Audit B8). When
 * this string changes for a row that already has a `serverId`, the row was
 * edited in-canvas and must be PATCHed so the server re-derives the billed
 * quantity. Annotation / color / group edits are intentionally excluded -
 * those are handled by the existing flows and do not move the quantity.
 */
function geometrySignature(m: Measurement): string {
  return JSON.stringify({
    p: m.points,
    d: m.depth ?? null,
    c: m.type === 'count' ? Math.round(m.value) : null,
    t: m.type,
    // The deduction flag flips a measurement between gross and void without
    // changing its geometry; include it so toggling it triggers a PATCH and
    // the server row stays in sync.
    x: m.type === 'area' ? Boolean(m.isDeduction) : false,
  });
}

/** Build the reshape PATCH body: just the geometry-bearing fields. The
 *  server recomputes `measurement_value` / `volume` / `perimeter` from
 *  these, so a client cannot inflate a quantity through this path. */
function toApiUpdate(m: Measurement, scale?: ScaleConfig): Partial<MeasurementCreate> {
  const ppu = scale && scale.pixelsPerUnit > 0 ? scale.pixelsPerUnit : null;
  return {
    points: m.points,
    type: m.type,
    scale_pixels_per_unit: ppu,
    depth: m.depth ?? null,
    count_value: m.type === 'count' ? Math.round(m.value) : null,
    is_deduction: m.type === 'area' ? Boolean(m.isDeduction) : false,
  };
}

function fromApiFormat(r: MeasurementResponse): Measurement {
  const meta = r.metadata || {};
  return {
    id: (meta.frontend_id as string) || r.id,
    serverId: r.id,
    type: r.type as Measurement['type'],
    points: r.points as Point[],
    value: r.measurement_value ?? r.count_value ?? 0,
    unit: displayUnit(r.measurement_unit),
    label: r.annotation || '',
    annotation: r.annotation || '',
    page: r.page,
    group: r.group_name,
    depth: r.depth ?? undefined,
    // Prefer the dedicated metadata.area; fall back to the canonical
    // server `volume`/`measurement_value` so an area survives even when
    // it was persisted before the dedicated field existed (D-TKC-031).
    area:
      (meta.area as number) ??
      (r.type === 'area' ? r.measurement_value ?? undefined : undefined),
    text: (meta.text as string) ?? undefined,
    color: r.group_color || undefined,
    width: (meta.width as number) ?? undefined,
    height: (meta.height as number) ?? undefined,
    isDeduction: r.is_deduction ?? undefined,
    linkedPositionId: r.linked_boq_position_id ?? undefined,
    linkedBoqId: (meta.linked_boq_id as string) ?? undefined,
    linkedPositionOrdinal: (meta.linked_position_ordinal as string) ?? undefined,
    linkedPositionLabel: (meta.linked_position_label as string) ?? undefined,
  };
}

/**
 * Reconstruct a {@link PageScales} from server measurements.
 *
 * Each row carries the ``scale_pixels_per_unit`` of the page it was drawn
 * on, so we take the most-recently-seen positive ratio per page as that
 * page's scale and the most common ratio across all pages as the document
 * default. Returns ``null`` when no row carries a usable ratio (the caller
 * then keeps whatever it already had). This restores per-page calibration
 * for a project opened on a device that has no localStorage copy.
 */
function pageScalesFromServer(rows: MeasurementResponse[]): PageScales | null {
  const byPage: Record<number, ScaleConfig> = {};
  const ratioFreq = new Map<number, number>();
  for (const r of rows) {
    const ppu = r.scale_pixels_per_unit;
    if (typeof ppu !== 'number' || !Number.isFinite(ppu) || ppu <= 0) continue;
    // Scale is metric-canonical (always metres); only the ratio differs per
    // page. Track frequency to pick the document default.
    byPage[r.page] = { pixelsPerUnit: ppu, unitLabel: 'm' };
    ratioFreq.set(ppu, (ratioFreq.get(ppu) ?? 0) + 1);
  }
  if (Object.keys(byPage).length === 0) return null;
  let bestRatio = 100;
  let bestCount = -1;
  for (const [ratio, count] of ratioFreq.entries()) {
    if (count > bestCount) {
      bestCount = count;
      bestRatio = ratio;
    }
  }
  return { defaultScale: { pixelsPerUnit: bestRatio, unitLabel: 'm' }, byPage };
}

/* ── Hook ─────────────────────────────────────────────────────────────── */

interface UseMeasurementPersistenceOptions {
  fileName: string | null;
  documentIdentity?: string | null;
  documentSource?: MeasurementDocumentSource | null;
  measurements: Measurement[];
  setMeasurements: (
    measurements: Measurement[] | ((prev: Measurement[]) => Measurement[]),
  ) => void;
  /** Per-page (per-sheet) scale model. Persisted whole; a legacy
   *  single-scale document is migrated into the default on load. */
  pageScales: PageScales;
  setPageScales: (pageScales: PageScales) => void;
  /** The current page's effective scale, sent as ``scale_pixels_per_unit``
   *  on measurements so the server B8 recompute uses the same ratio.
   *  (Per-measurement page scale is resolved from ``pageScales``.) */
  scale: ScaleConfig;
  /** Active project ID for backend sync. */
  projectId?: string | null;
}

interface UseMeasurementPersistenceResult {
  hasPersistedData: boolean;
  saveNow: () => void;
  clearPersisted: () => void;
  savedDocumentCount: number;
  /** Whether data is being synced to the server. */
  syncing: boolean;
  /** Whether server sync has been done at least once. */
  syncedToServer: boolean;
}

export function useMeasurementPersistence({
  fileName,
  documentIdentity,
  documentSource,
  measurements,
  setMeasurements,
  pageScales,
  setPageScales,
  scale,
  projectId,
}: UseMeasurementPersistenceOptions): UseMeasurementPersistenceResult {
  const hasPersistedRef = useRef(false);
  const lastScopeRef = useRef<string | null>(null);
  const lastLocalSaveSignatureRef = useRef<string | null>(null);
  const [isHydrated, setIsHydrated] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncedToServer, setSyncedToServer] = useState(false);
  const serverSyncRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Reshape-PATCH tracking (#194 Feature 1). `geometrySigRef` remembers the
  // last geometry we know the server has for each `serverId`, so we only
  // PATCH a row whose geometry actually changed. `patchTimerRef` debounces
  // and `inFlightPatchRef` coalesces rapid reshapes of the same row
  // (last-write-wins) so mid-drag churn never floods the network.
  const geometrySigRef = useRef<Map<string, string>>(new Map());
  const patchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightPatchRef = useRef<Set<string>>(new Set());
  const inFlightSyncRef = useRef<Set<string>>(new Set());
  // Read the QueryClient directly from context — ``useContext`` returns
  // ``undefined`` instead of throwing when the provider is absent (e.g. in
  // unit tests that render the hook in isolation). When present, we use
  // it to broadcast a refresh to the unified Markups hub.
  const qc = useContext(QueryClientContext);

  // Load persisted data when the stable document id or local filename changes.
  // Server sync uses only stable document ids; localStorage also supports a
  // filename fallback so local-only PDFs survive remounts without leaking into
  // the backend measurement namespace.
  useEffect(() => {
    const documentId = documentIdentity?.trim() || fileName?.trim() || null;
    if (!documentId) {
      setMeasurements([]);
      hasPersistedRef.current = false;
      setSyncedToServer(false);
      setIsHydrated(false);
      lastScopeRef.current = null;
      lastLocalSaveSignatureRef.current = null;
      inFlightSyncRef.current = new Set();
      return;
    }
    const stableDocumentId = documentId;
    const stableProjectId = projectId || undefined;
    const scopeKey = `${stableProjectId || 'local'}:${stableDocumentId}`;
    if (scopeKey === lastScopeRef.current) return;
    lastScopeRef.current = scopeKey;
    setSyncedToServer(false);
    setIsHydrated(false);
    lastLocalSaveSignatureRef.current = null;
    geometrySigRef.current = new Map();
    inFlightSyncRef.current = new Set();
    setMeasurements([]);

    let cancelled = false;

    async function loadData() {
      const loadLocalData = (): PersistedDocument | null => {
        let data = loadFromStorage(stableProjectId, stableDocumentId);
        if (!data && !stableProjectId && fileName) {
          try {
            const raw = localStorage.getItem(legacyDocKey(fileName));
            data = raw ? (JSON.parse(raw) as PersistedDocument) : null;
          } catch {
            data = null;
          }
        }
        return data;
      };

      // Try server first only when the document has a database identity.
      if (stableProjectId && documentIdentity?.trim()) {
        try {
          const serverData = await takeoffApi.list(stableProjectId, stableDocumentId);
          if (!cancelled && serverData.length > 0) {
            hasPersistedRef.current = true;
            setSyncedToServer(true);
            const mapped = serverData.map(fromApiFormat);
            // Seed the geometry baseline so a fresh load never re-PATCHes
            // rows that already match the server (#194).
            geometrySigRef.current = new Map(
              mapped
                .filter((m) => m.serverId)
                .map((m) => [m.serverId as string, geometrySignature(m)]),
            );
            const localData = loadLocalData();
            const serverIds = new Set(
              mapped.flatMap((m) => [m.id, m.serverId].filter((id): id is string => Boolean(id))),
            );
            // Keep server rows authoritative once they exist, but preserve
            // local-only rows that were drawn before the debounced server sync
            // completed. Otherwise a fast reload after two measurements can
            // hydrate from a one-row server response and overwrite the still
            // richer local fallback.
            const unsyncedLocal = (localData?.measurements ?? [])
              .filter((m) => !m.suggested)
              .filter((m) => {
                if (m.serverId) return false; // Synced but missing from server = deleted
                return !serverIds.has(m.id);
              });
            // Reconstruct the per-page scale from localStorage when present;
            // otherwise fall back to per-measurement ratios stored by the
            // server for a fresh browser/device.
            const fromServer = pageScalesFromServer(serverData);
            if (localData) {
              setPageScales(hydratePageScales(localData.pageScales, localData.scale));
            } else if (fromServer) {
              setPageScales(fromServer);
            }
            setMeasurements([...mapped, ...unsyncedLocal]);
            setIsHydrated(true);
            return;
          }
        } catch {
          // Server unavailable — fall through to localStorage
        }
      }

      // Fallback to localStorage
      if (!cancelled) {
        const data = loadLocalData();
        if (data) {
          hasPersistedRef.current = true;
          setMeasurements(data.measurements);
          // Graceful migration: a document saved before per-page scale only
          // carried ``data.scale``; hydratePageScales promotes it to the
          // document default so every page reads the same number it always
          // did until the user re-calibrates an individual sheet.
          setPageScales(hydratePageScales(data.pageScales, data.scale));
        } else {
          hasPersistedRef.current = false;
        }
        setIsHydrated(true);
      }
    }

    loadData();
    return () => { cancelled = true; };
  }, [documentIdentity, fileName, projectId, setMeasurements, setPageScales]);

  // Auto-save to localStorage as soon as React commits measurement state. This
  // is the reload-safe fallback while server sync is debounced; waiting for
  // normal effects, or for the initial server hydration request to finish, can
  // lose a freshly drawn measurement when the user refreshes right after
  // drawing.
  useLayoutEffect(() => {
    const documentId = documentIdentity?.trim() || fileName?.trim() || null;
    if (!documentId) return;
    const scopeKey = `${projectId || 'local'}:${documentId}`;
    if (lastScopeRef.current !== null && scopeKey !== lastScopeRef.current) return;
    const persistedMeasurements = measurements.filter((m) => !m.suggested);
    if (!isHydrated && persistedMeasurements.length === 0) return;
    // Never persist AI suggestions: only confirmed measurements are saved.
    // Persist BOTH the new per-page model and the legacy single ``scale``
    // (the current page's, as a best-effort default) so a downgrade to an
    // older build that only reads ``scale`` still finds a usable value.
    const localSaveSignature = JSON.stringify({
      scopeKey,
      measurements: persistedMeasurements,
      pageScales,
      scale,
    });
    if (localSaveSignature === lastLocalSaveSignatureRef.current) return;
    const saved = saveToStorage(projectId, documentId, {
      measurements: persistedMeasurements,
      pageScales,
      scale,
      savedAt: Date.now(),
    });
    if (saved) {
      lastLocalSaveSignatureRef.current = localSaveSignature;
    }
  }, [isHydrated, documentIdentity, fileName, projectId, measurements, pageScales, scale]);

  // Auto-sync to server with debounce (3s). Both measurement and annotation
  // types persist now (v2.6.7) — backend schema accepts the full set.
  useEffect(() => {
    const documentId = documentIdentity?.trim() || null;
    if (!isHydrated || !documentId || !projectId) return;
    if (measurements.length === 0) return;
    const serverMeasurements = measurements;

    if (serverSyncRef.current) clearTimeout(serverSyncRef.current);
    serverSyncRef.current = null;
    const toCreate = serverMeasurements
      // Suggested-but-unconfirmed measurements are excluded; accepting a
      // suggestion clears `suggested` and the next tick syncs it (#194).
      .filter((m) => !m.serverId && !m.suggested && !inFlightSyncRef.current.has(m.id))
      // Per-page scale: toApiFormat resolves each row's own page scale
      // from pageScales, so a multi-sheet set syncs correct ratios.
      .map((m) => toApiFormat(m, projectId, documentId, pageScales, documentSource));
    if (toCreate.length === 0) {
      if (!serverMeasurements.some((m) => !m.serverId && !m.suggested)) {
        setSyncedToServer(true);
      }
      return;
    }

    serverSyncRef.current = setTimeout(async () => {
      setSyncing(true);
      try {
        toCreate.forEach((m) => {
          const fid = m.metadata?.frontend_id;
          if (typeof fid === 'string') {
            inFlightSyncRef.current.add(fid);
          }
        });

        try {
          const created = await takeoffApi.bulkCreate(toCreate);
          const createdByFrontendId = new Map<string, MeasurementResponse>();
          for (const c of created) {
            const fid = c.metadata?.frontend_id;
            if (typeof fid === 'string') createdByFrontendId.set(fid, c);
          }
          const synced = serverMeasurements
            .map((m) => {
              if (m.serverId) return null;
              const match = createdByFrontendId.get(m.id);
              return match ? { measurement: m, serverId: match.id } : null;
            })
            .filter((x): x is { measurement: Measurement; serverId: string } => x !== null);
          // Update serverId on created measurements using functional updater to avoid stale state races
          setMeasurements((prev) =>
            prev.map((m) => {
              if (m.serverId) return m;
              const match = createdByFrontendId.get(m.id);
              return match ? { ...m, serverId: match.id } : m;
            })
          );
          for (const { measurement, serverId } of synced) {
            // Seed the reshape baseline for the freshly-synced row so a later
            // in-canvas edit PATCHes, but a no-op tick does not (#194).
            geometrySigRef.current.set(serverId, geometrySignature(measurement));
            inFlightSyncRef.current.delete(measurement.id);
          }
          // Surface the new measurements in the unified Markups hub.
          qc?.invalidateQueries({ queryKey: ['unified-markups'] });
        } catch (err) {
          toCreate.forEach((m) => {
            const fid = m.metadata?.frontend_id;
            if (typeof fid === 'string') {
              inFlightSyncRef.current.delete(fid);
            }
          });
          throw err;
        }
        setSyncedToServer(true);
      } catch {
        // Server sync failed — data safe in localStorage
      } finally {
        setSyncing(false);
        serverSyncRef.current = null;
      }
    }, 3000);

    return () => {
      if (serverSyncRef.current) clearTimeout(serverSyncRef.current);
      serverSyncRef.current = null;
    };
  }, [isHydrated, documentIdentity, documentSource, projectId, measurements, setMeasurements, pageScales]);

  // Reshape PATCH (#194 Feature 1). When a measurement that already has a
  // `serverId` has its geometry changed in-canvas, PATCH just that row so
  // the server re-derives the billed quantity (Audit B8). Debounced 400ms
  // off the last change; mid-drag churn never reaches the network because
  // the viewer only commits points on mouseup. Coalesced per `serverId`:
  // if a row is already in-flight we skip it this tick and the changed
  // signature keeps it dirty for the next pass (last-write-wins per row).
  useEffect(() => {
    if (!isHydrated) return;
    if (!projectId) return;
    if (measurements.length === 0) return;

    // Find synced rows whose geometry drifted from the server baseline.
    const dirty = measurements.filter((m) => {
      if (!m.serverId || m.suggested) return false;
      const prevSig = geometrySigRef.current.get(m.serverId);
      // No baseline yet (e.g. a row hydrated before its baseline seeded)
      // -> record the current signature without firing a PATCH.
      if (prevSig === undefined) {
        geometrySigRef.current.set(m.serverId, geometrySignature(m));
        return false;
      }
      return prevSig !== geometrySignature(m);
    });
    if (dirty.length === 0) return;

    if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
    patchTimerRef.current = setTimeout(async () => {
      // Re-filter dirty rows using the latest geometrySigRef values. This prevents
      // redundant PATCH requests if a previous in-flight sync resolved while this
      // timer was waiting.
      const activeDirty = dirty.filter((m) => {
        const prevSig = geometrySigRef.current.get(m.serverId!);
        return prevSig !== geometrySignature(m);
      });
      if (activeDirty.length === 0) return;

      const reconciled: { frontendId: string; value: number; area?: number }[] = [];
      await Promise.all(
        activeDirty.map(async (m) => {
          const serverId = m.serverId!;
          if (inFlightPatchRef.current.has(serverId)) return; // coalesce
          inFlightPatchRef.current.add(serverId);
          const sig = geometrySignature(m);
          try {
            // Per-page scale: PATCH with the measurement's own page scale so
            // the server B8 recompute uses the ratio that sheet was drawn at.
            const updated = await takeoffApi.update(
              serverId,
              toApiUpdate(m, scaleForPage(pageScales, m.page)),
            );
            // Mark this geometry as known-on-server so we don't re-PATCH it.
            geometrySigRef.current.set(serverId, sig);
            // Overwrite the optimistic value with the server-authoritative
            // recompute so the displayed quantity can never exceed what the
            // geometry justifies.
            const serverValue =
              updated.measurement_value ?? updated.volume ?? updated.count_value ?? m.value;
            reconciled.push({
              frontendId: m.id,
              value: serverValue,
              area: (updated.metadata?.area as number) ?? updated.measurement_value ?? undefined,
            });
          } catch {
            // PATCH failed - keep the optimistic value + the localStorage
            // copy (the 500ms effect above already persisted it). Leave the
            // signature stale so the next tick retries.
          } finally {
            inFlightPatchRef.current.delete(serverId);
          }
        }),
      );

      if (reconciled.length > 0) {
        const reconciledByFrontendId = new Map(
          reconciled.map((r) => [r.frontendId, r]),
        );
        setMeasurements((prev) =>
          prev.map((m) => {
            const r = reconciledByFrontendId.get(m.id);
            if (!r) return m;
            return {
              ...m,
              value: r.value,
              ...(m.type === 'volume' && r.area !== undefined ? { area: r.area } : {}),
            };
          }),
        );
        qc?.invalidateQueries({ queryKey: ['unified-markups'] });
      }
    }, 400);

    return () => {
      if (patchTimerRef.current) clearTimeout(patchTimerRef.current);
    };
  }, [isHydrated, projectId, measurements, setMeasurements, pageScales, qc]);

  const saveNow = useCallback(() => {
    const documentId = documentIdentity?.trim() || fileName?.trim() || null;
    if (!documentId) return;
    saveToStorage(projectId, documentId, { measurements, pageScales, scale, savedAt: Date.now() });
  }, [documentIdentity, fileName, projectId, measurements, pageScales, scale]);

  const clearPersisted = useCallback(() => {
    const documentId = documentIdentity?.trim() || fileName?.trim() || null;
    if (!documentId) return;
    removeFromStorage(projectId, documentId, fileName);
    hasPersistedRef.current = false;
    lastLocalSaveSignatureRef.current = null;
  }, [documentIdentity, fileName, projectId]);

  return {
    hasPersistedData: hasPersistedRef.current,
    saveNow,
    clearPersisted,
    savedDocumentCount: getDocumentIndex().length,
    syncing,
    syncedToServer,
  };
}
