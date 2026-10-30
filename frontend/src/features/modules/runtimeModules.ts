import { useQuery } from '@tanstack/react-query';
import {
  Box,
  Calculator,
  BarChart3,
  Clipboard,
  FileText,
  Layers,
  Map as MapIcon,
  Package,
  Puzzle,
  Table,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/** A page declared by a ZIP-installed module (module.json `ui`), validated by the server. */
export interface RuntimeUiEntry {
  module: string;
  label: string;
  group: string;
  icon: string;
  mode: 'hosted';
  path: string;
  project_param: string | null;
}

/** Mirrors ALLOWED_ICONS in backend/app/core/module_package.py. */
export const RUNTIME_MODULE_ICONS: Record<string, LucideIcon> = {
  package: Package,
  puzzle: Puzzle,
  box: Box,
  layers: Layers,
  table: Table,
  chart: BarChart3,
  calculator: Calculator,
  file: FileText,
  clipboard: Clipboard,
  wrench: Wrench,
  map: MapIcon,
};

export const RUNTIME_UI_ENTRIES_KEY = ['module-ui-entries'] as const;

export function runtimeModuleRoute(module: string): string {
  return `/modules/runtime/${module}`;
}

export function useRuntimeUiEntries() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return useQuery({
    queryKey: RUNTIME_UI_ENTRIES_KEY,
    queryFn: () => apiGet<RuntimeUiEntry[]>('/v1/module-packages/ui-entries'),
    enabled: isAuthenticated,
    staleTime: 60 * 1000,
  });
}

/** Version 1 of the message the shell sends to a hosted module page. */
export interface HostContextMessage {
  oe: 'context';
  v: 1;
  module: string;
  project_id: string | null;
  theme: 'light' | 'dark';
  locale: string;
  api_base: string;
  token: string;
  token_expires_at: string;
}

/** Messages a hosted page may send. Anything else is ignored. */
export type GuestMessage = { oe: 'ready' } | { oe: 'token' } | { oe: 'navigate'; to: string } | { oe: 'title'; title: string };

export function parseGuestMessage(data: unknown): GuestMessage | null {
  if (!data || typeof data !== 'object') return null;
  const msg = data as Record<string, unknown>;
  if (msg.oe === 'ready' || msg.oe === 'token') return { oe: msg.oe };
  // Only in-app paths: no scheme, no protocol-relative, no backslash tricks.
  if (msg.oe === 'navigate' && typeof msg.to === 'string' && /^\/(?![/\\])[^\s\\]*$/.test(msg.to)) {
    return { oe: 'navigate', to: msg.to };
  }
  if (msg.oe === 'title' && typeof msg.title === 'string') return { oe: 'title', title: msg.title.slice(0, 80) };
  return null;
}

/** The iframe URL: the declared path, plus the active project when the module asked for it. */
export function hostedSrc(entry: RuntimeUiEntry, projectId: string | null): string {
  if (!entry.project_param || !projectId) return entry.path;
  return `${entry.path}?${encodeURIComponent(entry.project_param)}=${encodeURIComponent(projectId)}`;
}
