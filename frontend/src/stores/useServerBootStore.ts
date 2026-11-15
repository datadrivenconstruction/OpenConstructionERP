/**
 * Whether the server has finished starting.
 *
 * The backend opens its port at once and runs startup (schema, modules,
 * baseline data) behind it. Until that is done `/api/health` and every API call
 * answer 503 with a `boot` block naming the phase. `ServerStartingGate` reads
 * this store to show the setup screen instead of pages that would only fail.
 */

import { create } from 'zustand';

export interface BootSnapshot {
  status: 'starting' | 'failed' | 'ready';
  phase: string;
  step: number;
  steps: number;
  elapsed_seconds: number;
  phase_elapsed_seconds: number;
}

/** `checking`: the first health answer has not arrived yet. */
export type ServerBootPhase = 'checking' | 'starting' | 'failed' | 'ready';

interface ServerBootState {
  phase: ServerBootPhase;
  boot: BootSnapshot | null;
  report: (boot: BootSnapshot) => void;
  setReady: () => void;
}

export const useServerBootStore = create<ServerBootState>((set) => ({
  phase: 'checking',
  boot: null,
  report: (boot) => set({ boot, phase: boot.status === 'failed' ? 'failed' : boot.status === 'ready' ? 'ready' : 'starting' }),
  setReady: () => set({ phase: 'ready' }),
}));

function asBootSnapshot(value: unknown): BootSnapshot | null {
  if (!value || typeof value !== 'object') return null;
  const boot = (value as { boot?: unknown }).boot;
  if (!boot || typeof boot !== 'object') return null;
  const b = boot as Partial<BootSnapshot>;
  if (typeof b.phase !== 'string' || (b.status !== 'starting' && b.status !== 'failed')) return null;
  return {
    status: b.status,
    phase: b.phase,
    step: typeof b.step === 'number' ? b.step : 0,
    steps: typeof b.steps === 'number' ? b.steps : 0,
    elapsed_seconds: typeof b.elapsed_seconds === 'number' ? b.elapsed_seconds : 0,
    phase_elapsed_seconds: typeof b.phase_elapsed_seconds === 'number' ? b.phase_elapsed_seconds : 0,
  };
}

/** Parse a 503 body; null when it is not the server's "still starting" answer. */
export function parseBootBody(status: number, body: unknown): BootSnapshot | null {
  if (status !== 503) return null;
  return asBootSnapshot(body);
}

/** Called by the API client for every error response: flips the gate back on. */
export function reportIfServerStarting(status: number, body: unknown): void {
  const boot = parseBootBody(status, body);
  if (boot) useServerBootStore.getState().report(boot);
}
