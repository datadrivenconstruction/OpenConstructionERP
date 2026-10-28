// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import type { AgentDescriptor } from '../api';
import { AgentCard } from './AgentCard';
import {
  resolveCategoryMeta,
  categorySortIndex,
  normaliseCategory,
} from './agentMeta';

interface AgentGalleryProps {
  agents: AgentDescriptor[];
  selectedName: string | null;
  onSelect: (agent: AgentDescriptor) => void;
  onPromptPick: (agent: AgentDescriptor, prompt: string) => void;
  /** Edit a custom agent (only ever called for is_custom agents). */
  onEdit?: (agent: AgentDescriptor) => void;
  /** Delete a custom agent (only ever called for is_custom agents). */
  onDelete?: (agent: AgentDescriptor) => void;
}

interface CategoryGroup {
  key: string;
  agents: AgentDescriptor[];
}

/**
 * The agent catalogue, grouped into category sections (estimating, quality,
 * documents, analytics, …) each with a labelled header. Agents render as
 * rich, selectable cards.
 */
export function AgentGallery({
  agents,
  selectedName,
  onSelect,
  onPromptPick,
  onEdit,
  onDelete,
}: AgentGalleryProps): JSX.Element {
  const { t } = useTranslation();

  const groups = useMemo<CategoryGroup[]>(() => {
    const byCategory = new Map<string, AgentDescriptor[]>();
    for (const agent of agents) {
      // The caller's own custom agents collect into a single "Your agents"
      // section at the top, regardless of the category they were filed under,
      // so a user always finds their creations together.
      const key = agent.is_custom ? 'my_agents' : normaliseCategory(agent.category);
      const bucket = byCategory.get(key);
      if (bucket) bucket.push(agent);
      else byCategory.set(key, [agent]);
    }
    return [...byCategory.entries()]
      .map(([key, list]) => ({ key, agents: list }))
      .sort((a, b) => {
        const byIndex = categorySortIndex(a.key) - categorySortIndex(b.key);
        return byIndex !== 0 ? byIndex : a.key.localeCompare(b.key);
      });
  }, [agents]);

  // When every agent shares the single fallback category there is nothing to
  // group by, so skip the section header to avoid a redundant "General" label.
  const showHeaders = groups.length > 1 || (groups[0]?.key ?? 'general') !== 'general';

  return (
    <div className="space-y-8">
      {groups.map((group) => {
        const meta = resolveCategoryMeta(group.key);
        const SectionIcon = meta.icon;
        return (
          <section key={group.key} className="space-y-3">
            {showHeaders && (
              <header className="flex items-center gap-2">
                <span
                  className={`flex h-7 w-7 items-center justify-center rounded-lg ${meta.chip}`}
                >
                  <SectionIcon className="h-4 w-4" aria-hidden="true" />
                </span>
                <h3 className="text-sm font-semibold text-content-primary">
                  {t(`agents.category.${group.key}`, { defaultValue: meta.label })}
                </h3>
                <span className="text-xs text-content-tertiary">{group.agents.length}</span>
              </header>
            )}
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {group.agents.map((agent) => (
                <AgentCard
                  key={agent.name}
                  agent={agent}
                  selected={selectedName === agent.name}
                  onSelect={() => onSelect(agent)}
                  onPromptPick={(prompt) => onPromptPick(agent, prompt)}
                  onEdit={agent.is_custom && onEdit ? () => onEdit(agent) : undefined}
                  onDelete={agent.is_custom && onDelete ? () => onDelete(agent) : undefined}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
