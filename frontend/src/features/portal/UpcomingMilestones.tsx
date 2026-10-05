// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "What happens next on my project": the milestones the builder marked for
// the client, due in the next two weeks or already late. The card hides
// itself when there is nothing to show, so a client whose builder marks no
// milestones never sees an empty box.

import { useQueries, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Flag } from 'lucide-react';
import { Badge, Card } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { listMyProjects, listProjectMilestones, type PortalMilestone } from './api';

export function UpcomingMilestones() {
  const { t } = useTranslation();

  const projectsQ = useQuery({
    queryKey: ['portal-home', 'projects'],
    queryFn: () => listMyProjects(),
    staleTime: 60_000,
  });
  const projects = projectsQ.data ?? [];

  const milestoneQs = useQueries({
    queries: projects.map((p) => ({
      queryKey: ['portal-home', 'milestones', p.id],
      queryFn: () => listProjectMilestones(p.id),
      staleTime: 60_000,
    })),
  });

  const groups = projects
    .map((p, i) => ({ project: p, items: milestoneQs[i]?.data?.items ?? [] }))
    .filter((g) => g.items.length > 0);
  if (groups.length === 0) return null;
  const showProjectNames = projects.length > 1;

  return (
    <Card padding="none" className="w-full">
      <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
        <Flag size={16} className="text-oe-blue" />
        <h2 className="text-sm font-semibold text-content-primary">
          {t('homeportal.milestones_title', { defaultValue: 'Coming up on your project' })}
        </h2>
      </div>
      <div className="divide-y divide-border-light">
        {groups.map(({ project, items }) => (
          <section key={project.id} className="px-4 py-3">
            {showProjectNames && (
              <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {project.name}
              </p>
            )}
            <ul className="space-y-2">
              {items.map((m) => (
                <MilestoneRow key={m.id} milestone={m} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Card>
  );
}

function MilestoneRow({ milestone: m }: { milestone: PortalMilestone }) {
  const { t } = useTranslation();
  const moved = m.expected_date !== m.planned_date;

  let badge: { variant: 'error' | 'warning' | 'blue'; text: string };
  if (m.is_late) {
    badge = {
      variant: 'error',
      text: t('homeportal.milestone_late', {
        count: -m.days_until,
        defaultValue_one: '{{count}} day late',
        defaultValue_other: '{{count}} days late',
      }),
    };
  } else if (m.days_until === 0) {
    badge = { variant: 'warning', text: t('homeportal.milestone_today', { defaultValue: 'Today' }) };
  } else {
    badge = {
      variant: 'blue',
      text: t('homeportal.milestone_in_days', {
        count: m.days_until,
        defaultValue_one: 'In {{count}} day',
        defaultValue_other: 'In {{count}} days',
      }),
    };
  }

  return (
    <li className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-content-primary">{m.name}</p>
        <p className="text-xs text-content-secondary">
          <DateDisplay value={m.expected_date} />
        </p>
        {moved && (
          <p className="text-2xs text-content-tertiary">
            <span>{t('homeportal.milestone_originally', { defaultValue: 'Originally planned' })}</span>{' '}
            <DateDisplay value={m.planned_date} />
          </p>
        )}
      </div>
      <Badge variant={badge.variant} dot>
        {badge.text}
      </Badge>
    </li>
  );
}
