// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// "Run agent" entry point for record screens: opens the project catalogue with the agent preselected.
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Bot } from 'lucide-react';

import { catalogueRunLink, type CatalogueAgentName } from '../catalogueApi';

export function RunAgentButton({
  agent,
  inputs,
  className,
}: {
  agent: CatalogueAgentName;
  inputs?: Record<string, string>;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <Link
      to={catalogueRunLink(agent, inputs)}
      data-testid={`run-agent-${agent}`}
      className={
        className ??
        'inline-flex h-9 items-center gap-1.5 rounded-lg border border-border-light px-3 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
      }
    >
      <Bot className="h-4 w-4" />
      {t(`project_agents.run_entry.${agent}`, {
        defaultValue:
          agent === 'rfi_drafter'
            ? 'Draft RFI with agent'
            : agent === 'daily_reporter'
              ? 'Draft report with agent'
              : agent === 'clause_reviewer'
                ? 'Review clauses with agent'
                : 'Check with agent',
      })}
    </Link>
  );
}
