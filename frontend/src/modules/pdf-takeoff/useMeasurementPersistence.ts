import { useCallback, useEffect, useRef, useState } from 'react';
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

/* ── Convert between frontend Measurement and backend API format ─────── */

function toApiFormat(m: Measurement, projectId: string, documentId: string): MeasurementCreate {
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
    measurement_unit: m.unit || 'm',
    depth: m.depth ?? null,
    volume: m.type === 'volume' ? m.value : null,
    count_value: m.type === 'count' ? Math.round(m.value) : null,
    scale_pixels_per_unit: null,
    metadata: {
      text: m.text,
      width: m.width,
      height: m.height,
      area: m.area,
      frontend_id: m.id,
    },
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
    unit: r.measurement_unit,
    label: r.annotation || '',
    annotation: r.annotation || '',
    page: r.page,
    group: r.group_name,
    depth: r.depth ?? undefined,
    area: (meta.area as number) ?? undefined,
    text: (meta.text as string) ?? undefined,
    color: r.group_color || undefined,
    width: (meta.width as number) ?? undefined,
    height: (meta.height as number) ?? undefined,
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

  // Load persisted data when file name changes — try server first, fallback to localStorage
  useEffect(() => {
    if (!fileName || fileName === lastFileRef.current) return;
    lastFileRef.current = fileName;

    let cancelled = false;

    async function loadData() {
      // Try server first if project is available
      if (projectId) {
        try {
          const serverData = await takeoffApi.list(projectId, fileName);
          if (!cancelled && serverData.length > 0) {
            hasPersistedRef.current = true;
            setSyncedToServer(true);
            setMeasurements(serverData.map(fromApiFormat));
            return;
          }
        } catch {
          // Server unavailable — fall through to localStorage
        }
      }

      // Fallback to localStorage
      if (!cancelled) {
        const data = loadFromStorage(fileName);
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
      saveToStorage(fileName, { measurements, scale, savedAt: Date.now() });
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [fileName, measurements, scale]);

  // Auto-sync to server with debounce (3s) — only measurement types, not annotations
  useEffect(() => {
    if (!fileName || !projectId) return;
    const measurementTypes = ['distance', 'polyline', 'area', 'volume', 'count'];
    const serverMeasurements = measurements.filter((m) => measurementTypes.includes(m.type));
    if (serverMeasurements.length === 0) return;

    if (serverSyncRef.current) clearTimeout(serverSyncRef.current);
    serverSyncRef.current = setTimeout(async () => {
      setSyncing(true);
      try {
        const toCreate = serverMeasurements
          .filter((m) => !m.serverId)
          .map((m) => toApiFormat(m, projectId, fileName));

        if (toCreate.length > 0) {
          const created = await takeoffApi.bulkCreate(toCreate);
          // Update serverId on created measurements
          setMeasurements(measurements.map((m) => {
            if (m.serverId) return m;
            const match = created.find((c) =>
              (c.metadata?.frontend_id as string) === m.id
            );
            return match ? { ...m, serverId: match.id } : m;
          }));
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
  }, [fileName, projectId, measurements, setMeasurements]);

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
