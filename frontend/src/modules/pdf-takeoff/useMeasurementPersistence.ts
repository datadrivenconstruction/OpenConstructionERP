import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { QueryClientContext } from '@tanstack/react-query';
import { takeoffApi, type MeasurementCreate, type MeasurementResponse } from '@/features/takeoff/api';

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
  scale: ScaleConfig;
  savedAt: number;
}

/* ── localStorage helpers (fallback) ─────────────────────────────────── */

const STORAGE_PREFIX = 'oe_takeoff_';
const INDEX_KEY = 'oe_takeoff_index';

function docKey(fileName: string): string {
  return `${STORAGE_PREFIX}${fileName.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
}

function loadFromStorage(fileName: string): PersistedDocument | null {
  try {
    const raw = localStorage.getItem(docKey(fileName));
    if (!raw) return null;
    return JSON.parse(raw) as PersistedDocument;
  } catch {
    return null;
  }
}

function saveToStorage(fileName: string, data: PersistedDocument): void {
  try {
    localStorage.setItem(docKey(fileName), JSON.stringify(data));
    const index = getDocumentIndex();
    if (!index.includes(fileName)) {
      index.push(fileName);
      localStorage.setItem(INDEX_KEY, JSON.stringify(index));
    }
  } catch {
    // localStorage full — silently fail
  }
}

export function removeFromStorage(fileName: string): void {
  try {
    localStorage.removeItem(docKey(fileName));
    const index = getDocumentIndex().filter((n) => n !== fileName);
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
  scale?: ScaleConfig,
): MeasurementCreate {
  // Area measurements carry the polygon area in `m.value`; volume
  // measurements carry the area separately in `m.area`. Persist the
  // canonical dimension fields so bim_hub quantity sync / BOQ linking
  // can pick the right quantity instead of guessing from the unit
  // string alone (D-TKC-031).
  const areaValue =
    m.type === 'area' ? m.value : m.type === 'volume' ? (m.area ?? null) : null;
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
    linkedPositionId: r.linked_boq_position_id ?? undefined,
    linkedBoqId: (meta.linked_boq_id as string) ?? undefined,
    linkedPositionOrdinal: (meta.linked_position_ordinal as string) ?? undefined,
    linkedPositionLabel: (meta.linked_position_label as string) ?? undefined,
  };
}

/* ── Hook ─────────────────────────────────────────────────────────────── */

interface UseMeasurementPersistenceOptions {
  fileName: string | null;
  measurements: Measurement[];
  setMeasurements: (measurements: Measurement[]) => void;
  scale: ScaleConfig;
  setScale: (scale: ScaleConfig) => void;
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
  measurements,
  setMeasurements,
  scale,
  setScale,
  projectId,
}: UseMeasurementPersistenceOptions): UseMeasurementPersistenceResult {
  const hasPersistedRef = useRef(false);
  const lastFileRef = useRef<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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
  // Read the QueryClient directly from context — ``useContext`` returns
  // ``undefined`` instead of throwing when the provider is absent (e.g. in
  // unit tests that render the hook in isolation). When present, we use
  // it to broadcast a refresh to the unified Markups hub.
  const qc = useContext(QueryClientContext);

  // Load persisted data when file name changes — try server first, fallback to localStorage
  useEffect(() => {
    if (!fileName || fileName === lastFileRef.current) return;
    lastFileRef.current = fileName;

    let cancelled = false;

    async function loadData() {
      // Try server first if project is available
      if (projectId) {
        try {
          const serverData = await takeoffApi.list(projectId, fileName ?? undefined);
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
            setMeasurements(mapped);
            return;
          }
        } catch {
          // Server unavailable — fall through to localStorage
        }
      }

      // Fallback to localStorage
      if (!cancelled) {
        const data = loadFromStorage(fileName!);
        if (data) {
          hasPersistedRef.current = true;
          setMeasurements(data.measurements);
          setScale(data.scale);
        } else {
          hasPersistedRef.current = false;
        }
      }
    }

    loadData();
    return () => { cancelled = true; };
  }, [fileName, projectId, setMeasurements, setScale]);

  // Auto-save to localStorage with debounce (500ms)
  useEffect(() => {
    if (!fileName) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      // Never persist AI suggestions: only confirmed measurements are saved.
      saveToStorage(fileName, {
        measurements: measurements.filter((m) => !m.suggested),
        scale,
        savedAt: Date.now(),
      });
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [fileName, measurements, scale]);

  // Auto-sync to server with debounce (3s). Both measurement and annotation
  // types persist now (v2.6.7) — backend schema accepts the full set.
  useEffect(() => {
    if (!fileName || !projectId) return;
    if (measurements.length === 0) return;
    const serverMeasurements = measurements;

    if (serverSyncRef.current) clearTimeout(serverSyncRef.current);
    serverSyncRef.current = setTimeout(async () => {
      setSyncing(true);
      try {
        const toCreate = serverMeasurements
          // Suggested-but-unconfirmed measurements are excluded; accepting a
          // suggestion clears `suggested` and the next tick syncs it (#194).
          .filter((m) => !m.serverId && !m.suggested)
          .map((m) => toApiFormat(m, projectId, fileName, scale));

        if (toCreate.length > 0) {
          const created = await takeoffApi.bulkCreate(toCreate);
          // Update serverId on created measurements
          setMeasurements(measurements.map((m) => {
            if (m.serverId) return m;
            const match = created.find((c) =>
              (c.metadata?.frontend_id as string) === m.id
            );
            if (!match) return m;
            // Seed the reshape baseline for the freshly-synced row so a
            // later in-canvas edit PATCHes, but a no-op tick does not (#194).
            geometrySigRef.current.set(match.id, geometrySignature(m));
            return { ...m, serverId: match.id };
          }));
          // Surface the new measurements in the unified Markups hub.
          qc?.invalidateQueries({ queryKey: ['unified-markups'] });
        }
        setSyncedToServer(true);
      } catch {
        // Server sync failed — data safe in localStorage
      } finally {
        setSyncing(false);
      }
    }, 3000);

    return () => {
      if (serverSyncRef.current) clearTimeout(serverSyncRef.current);
    };
  }, [fileName, projectId, measurements, setMeasurements, scale.pixelsPerUnit]);

  // Reshape PATCH (#194 Feature 1). When a measurement that already has a
  // `serverId` has its geometry changed in-canvas, PATCH just that row so
  // the server re-derives the billed quantity (Audit B8). Debounced 400ms
  // off the last change; mid-drag churn never reaches the network because
  // the viewer only commits points on mouseup. Coalesced per `serverId`:
  // if a row is already in-flight we skip it this tick and the changed
  // signature keeps it dirty for the next pass (last-write-wins per row).
  useEffect(() => {
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
      const reconciled: { frontendId: string; value: number; area?: number }[] = [];
      await Promise.all(
        dirty.map(async (m) => {
          const serverId = m.serverId!;
          if (inFlightPatchRef.current.has(serverId)) return; // coalesce
          inFlightPatchRef.current.add(serverId);
          const sig = geometrySignature(m);
          try {
            const updated = await takeoffApi.update(serverId, toApiUpdate(m, scale));
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
        setMeasurements(
          measurements.map((m) => {
            const r = reconciled.find((x) => x.frontendId === m.id);
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
  }, [projectId, measurements, setMeasurements, scale, qc]);

  const saveNow = useCallback(() => {
    if (!fileName) return;
    saveToStorage(fileName, { measurements, scale, savedAt: Date.now() });
  }, [fileName, measurements, scale]);

  const clearPersisted = useCallback(() => {
    if (!fileName) return;
    removeFromStorage(fileName);
    hasPersistedRef.current = false;
  }, [fileName]);

  return {
    hasPersistedData: hasPersistedRef.current,
    saveNow,
    clearPersisted,
    savedDocumentCount: getDocumentIndex().length,
    syncing,
    syncedToServer,
  };
}
