import { useCallback, useEffect, useRef } from 'react';

/* ── Types (mirrored from TakeoffViewerModule) ──────────────────────── */

interface Point {
  x: number;
  y: number;
}

interface Measurement {
  id: string;
  type: 'distance' | 'polyline' | 'area' | 'volume' | 'count';
  points: Point[];
  value: number;
  unit: string;
  label: string;
  annotation: string;
  page: number;
  group: string;
  depth?: number;
  area?: number;
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

/* ── Storage helpers ──────────────────────────────────────────────────── */

const STORAGE_PREFIX = 'oe_takeoff_';
const INDEX_KEY = 'oe_takeoff_index';

/** Generate a stable storage key from file name. */
function docKey(fileName: string): string {
  return `${STORAGE_PREFIX}${fileName.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
}

/** Read persisted data for a document. */
function loadFromStorage(fileName: string): PersistedDocument | null {
  try {
    const raw = localStorage.getItem(docKey(fileName));
    if (!raw) return null;
    return JSON.parse(raw) as PersistedDocument;
  } catch {
    return null;
  }
}

/** Write persisted data for a document. */
function saveToStorage(fileName: string, data: PersistedDocument): void {
  try {
    localStorage.setItem(docKey(fileName), JSON.stringify(data));
    // Update document index (for listing saved documents)
    const index = getDocumentIndex();
    if (!index.includes(fileName)) {
      index.push(fileName);
      localStorage.setItem(INDEX_KEY, JSON.stringify(index));
    }
  } catch {
    // localStorage full or unavailable — silently fail
  }
}

/** Remove persisted data for a document. */
export function removeFromStorage(fileName: string): void {
  try {
    localStorage.removeItem(docKey(fileName));
    const index = getDocumentIndex().filter((n) => n !== fileName);
    localStorage.setItem(INDEX_KEY, JSON.stringify(index));
  } catch {
    // ignore
  }
}

/** List all saved document names. */
export function getDocumentIndex(): string[] {
  try {
    const raw = localStorage.getItem(INDEX_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

/* ── Hook ─────────────────────────────────────────────────────────────── */

interface UseMeasurementPersistenceOptions {
  /** Current PDF file name (null if no file loaded) */
  fileName: string | null;
  /** Current measurements state */
  measurements: Measurement[];
  /** Setter for measurements */
  setMeasurements: (measurements: Measurement[]) => void;
  /** Current scale config */
  scale: ScaleConfig;
  /** Setter for scale */
  setScale: (scale: ScaleConfig) => void;
}

interface UseMeasurementPersistenceResult {
  /** Whether data was loaded from storage on mount */
  hasPersistedData: boolean;
  /** Manually trigger a save */
  saveNow: () => void;
  /** Clear persisted data for the current document */
  clearPersisted: () => void;
  /** Number of saved documents in storage */
  savedDocumentCount: number;
}

/**
 * Auto-save and auto-load measurements per PDF document.
 * Data is persisted to localStorage keyed by file name.
 */
export function useMeasurementPersistence({
  fileName,
  measurements,
  setMeasurements,
  scale,
  setScale,
}: UseMeasurementPersistenceOptions): UseMeasurementPersistenceResult {
  const hasPersistedRef = useRef(false);
  const lastFileRef = useRef<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load persisted data when file name changes
  useEffect(() => {
    if (!fileName || fileName === lastFileRef.current) return;
    lastFileRef.current = fileName;

    const data = loadFromStorage(fileName);
    if (data) {
      hasPersistedRef.current = true;
      setMeasurements(data.measurements);
      setScale(data.scale);
    } else {
      hasPersistedRef.current = false;
    }
  }, [fileName, setMeasurements, setScale]);

  // Auto-save measurements with debounce (500ms)
  useEffect(() => {
    if (!fileName) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      saveToStorage(fileName, {
        measurements,
        scale,
        savedAt: Date.now(),
      });
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [fileName, measurements, scale]);

  const saveNow = useCallback(() => {
    if (!fileName) return;
    saveToStorage(fileName, {
      measurements,
      scale,
      savedAt: Date.now(),
    });
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
  };
}
