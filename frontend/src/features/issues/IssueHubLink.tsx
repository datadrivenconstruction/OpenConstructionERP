// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Back-link from an issue-owning module to the Unified Issue Hub.
 *
 * The hub unions five registers (`IssueSource` in `issueSources.ts`) and deep
 * links into each one. Until this component existed the traffic only ran that
 * way: the hub could reach every source, and no source could reach the hub.
 * The only references to `/issues` anywhere in the tree were the router, the
 * nav catalogue, the route icon map and the preload map, all of them app
 * infrastructure rather than a screen a user is looking at. Someone standing
 * in the NCR register had no way to learn that the four sibling registers
 * exist, short of finding the row in the sidebar.
 *
 * The link deliberately carries no source filter. The hub holds `filterSource`
 * state but reads no query parameters, so a `?source=ncr` would be inert; and
 * even once it is wired, preselecting the register the user just left would
 * show them what they already had. The point of arriving here is the other
 * four.
 */
import { CircleDot } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/shared/ui';

export interface IssueHubLinkProps {
  className?: string;
}

export function IssueHubLink({ className }: IssueHubLinkProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <Button
      variant="ghost"
      size="sm"
      className={className}
      onClick={() => navigate('/issues')}
      icon={<CircleDot size={14} />}
      title={t('issues.hub_link_hint', {
        defaultValue: 'Open the combined list of punch items, NCRs, clashes, mark-ups and model issues',
      })}
    >
      {t('issues.hub_link', { defaultValue: 'All issues' })}
    </Button>
  );
}

export default IssueHubLink;
