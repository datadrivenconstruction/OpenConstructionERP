// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Text and links for a process row. The API sends stable locale keys
 * (`processes.<id>.name|purpose|off_impact`) and the strings live in the
 * frontend locales. A service registered by a plugin that ships no strings
 * still reads as words: its id, humanised, never a raw key.
 */

import type { TFunction } from 'i18next';
import { useAuthStore } from '@/stores/useAuthStore';
import type { ProcessInfo } from './api';

function humanise(id: string): string {
  const s = id.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function processName(t: TFunction, p: ProcessInfo): string {
  return t(p.name_key || `processes.${p.id}.name`, { defaultValue: humanise(p.id) });
}

export function processPurpose(t: TFunction, p: ProcessInfo): string {
  return t(p.purpose_key || `processes.${p.id}.purpose`, { defaultValue: '' });
}

export function processOffImpact(t: TFunction, p: ProcessInfo): string {
  return t(p.off_impact_key || `processes.${p.id}.off_impact`, { defaultValue: '' });
}

export interface ModuleLink {
  id: string;
  label: string;
  to: string | null;
}

/**
 * Where a module chip leads. Backend module ids do not match menu entries one
 * to one, so the services that exist are mapped by hand; a module missing here
 * still shows its catalogue name, just without a link.
 */
const MODULE_ROUTES: Record<string, string> = {
  costs: '/costs',
  match: '/match-elements',
  search: '/costs',
  ai: '/ai-estimate',
  ai_agents: '/ai-agents',
  reporting: '/reporting',
  approval_routes: '/governance?tab=approvals',
  deadlines: '/deadlines',
  risk: '/risks',
  phonelog: '/phone-log',
  collaboration_locks: '/collaboration',
  notifications: '/notifications',
};

/** A module chip: the module's catalogue name and, when known, its page. */
export function moduleLink(t: TFunction, id: string): ModuleLink {
  const label = t(`modules.catalog.${id}`, { defaultValue: humanise(id.replace(/^oe_/, '')) });
  return { id, label, to: MODULE_ROUTES[id] ?? null };
}

export function formatMb(t: TFunction, mb: number): string {
  return mb >= 1024
    ? t('processes.ram_gb', { defaultValue: '{{value}} GB', value: (mb / 1024).toFixed(1) })
    : t('processes.ram_mb', { defaultValue: '{{value}} MB', value: Math.round(mb) });
}

const ADMIN_ROLES = new Set(['admin', 'owner', 'superuser']);

export function useIsProcessAdmin(): boolean {
  const role = useAuthStore((s) => s.userRole);
  return role != null && ADMIN_ROLES.has(role);
}
