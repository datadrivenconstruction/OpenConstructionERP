// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Tool picker for the custom-agent builder (Item 29).
//
// Lists every tool the runner can dispatch to and lets the operator grant a
// vetted subset to their agent. Each tool shows its required permission; tools
// the operator does not have permission to grant are disabled with a clear
// "needs <permission>" hint. The backend is the authority (it re-checks on
// save and returns a precise 403), so this client-side grey-out is a best-
// effort UX affordance, not a security boundary.
import { useTranslation } from 'react-i18next';
import { Wrench, Lock } from 'lucide-react';
import clsx from 'clsx';

import { useAuthStore } from '@/stores/useAuthStore';
import { ROLE_ALIASES, ROLE_RANK } from '@/shared/lib/roles';
import { toolLabel } from './agentMeta';
import type { ToolWithPermission } from '../api';

function rankOf(role: string): number | undefined {
  return (ROLE_RANK as Record<string, number>)[role];
}

// Minimum role each known tool permission requires (mirrors the modules'
// permission registrations — all VIEWER today). Unknown permissions fall back
// to "editor" so we never falsely enable a tool the backend will reject.
const PERMISSION_MIN_RANK: Record<string, number> = {
  'costs.read': ROLE_RANK.viewer,
  'assemblies.read': ROLE_RANK.viewer,
  'boq.read': ROLE_RANK.viewer,
  'boq.create': ROLE_RANK.viewer,
  'documents.read': ROLE_RANK.viewer,
  'projects.read': ROLE_RANK.viewer,
  'ai_agents.run': ROLE_RANK.editor,
};

// Resolves through ROLE_ALIASES by hand rather than through normalizeRole,
// and the difference is load bearing. normalizeRole maps an absent role to
// `viewer`; here that would be a grant, because ranks are compared rather than
// names, `viewer` ranks 0, and the read permissions above need 0. Leaving an
// unknown role without a rank is what makes the unknown case deny.
function canGrant(role: string | null, permission: string): boolean {
  const key = (role ?? '').toLowerCase();
  const resolved = ROLE_ALIASES[key] ?? key;
  const rank = rankOf(resolved);
  if (rank === undefined) return false;
  if (resolved === 'admin') return true;
  const need = PERMISSION_MIN_RANK[permission] ?? ROLE_RANK.editor;
  return rank >= need;
}

interface ToolPanelProps {
  tools: ToolWithPermission[];
  selected: string[];
  onChange: (next: string[]) => void;
  loading?: boolean;
}

export function ToolPanel({ tools, selected, onChange, loading }: ToolPanelProps): JSX.Element {
  const { t } = useTranslation();
  const userRole = useAuthStore((s) => s.userRole);

  const toggle = (name: string, allowed: boolean) => {
    if (!allowed) return;
    onChange(
      selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name],
    );
  };

  if (loading) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('agents.tools.loading', { defaultValue: 'Loading available tools…' })}
      </p>
    );
  }

  if (tools.length === 0) {
    return (
      <p className="text-xs text-content-tertiary">
        {t('agents.tools.none', { defaultValue: 'No tools are available to grant.' })}
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-2xs text-content-tertiary">
        {t('agents.tools.intro', {
          defaultValue:
            'Let this agent read your platform data with tools. You can only grant tools you already have access to.',
        })}
      </p>
      <ul className="space-y-1.5">
        {tools.map((tool) => {
          const friendly = toolLabel(tool.name);
          const allowed = canGrant(userRole, tool.required_permission);
          const checked = selected.includes(tool.name);
          return (
            <li key={tool.name}>
              <label
                className={clsx(
                  'flex items-start gap-2.5 rounded-lg border p-2.5 transition-colors',
                  allowed
                    ? 'cursor-pointer border-border-light bg-surface-secondary/40 hover:border-oe-blue/40'
                    : 'cursor-not-allowed border-border-light bg-surface-secondary/20 opacity-70',
                  checked && allowed && 'border-oe-blue/50 bg-oe-blue-subtle/60',
                )}
              >
                <input
                  type="checkbox"
                  checked={checked && allowed}
                  disabled={!allowed}
                  onChange={() => toggle(tool.name, allowed)}
                  className="mt-0.5 h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30 disabled:opacity-50"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-content-primary">
                    <Wrench className="h-3.5 w-3.5 text-oe-blue" aria-hidden="true" />
                    {friendly.label}
                  </span>
                  <span className="mt-0.5 block text-xs text-content-secondary">
                    {tool.description || friendly.hint}
                  </span>
                  {!allowed && (
                    <span className="mt-1 inline-flex items-center gap-1 rounded bg-semantic-warning-bg px-1.5 py-0.5 text-2xs font-medium text-[#b45309]">
                      <Lock className="h-3 w-3" aria-hidden="true" />
                      {t('agents.tools.needs_permission', {
                        defaultValue: 'Needs {{permission}}',
                        permission: tool.required_permission,
                      })}
                    </span>
                  )}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default ToolPanel;
