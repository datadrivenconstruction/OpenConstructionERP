// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Route wrapper for the model-issue register (BCF, the BIM Collaboration
 * Format). Resolves the active project and renders the register, which lists,
 * opens, comments on and imports or exports 3D model coordination topics with
 * their captured viewpoints and snapshots. The in-viewer "raise issue here"
 * capture is wired separately from the model viewer through useBcfCapture.
 */
import { useQuery } from '@tanstack/react-query';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { BcfIssuesPanel } from './BcfIssuesPanel';
import { IssueHubLink } from '@/features/issues/IssueHubLink';

export function BcfPage() {
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Array<{ id: string; name: string }>>(),
  });
  const projectId = activeProjectId || projects[0]?.id || '';
  return (
    <RequiresProject>
      {projectId ? (
        <>
          {/* This register has no PageHeader of its own, and the link lives on
              the route wrapper rather than inside BcfIssuesPanel because the
              panel is reused inside the model viewer, where the user has not
              navigated to a register and a link back to the hub is noise. */}
          <div className="mb-3 flex justify-end">
            <IssueHubLink />
          </div>
          <BcfIssuesPanel projectId={projectId} />
        </>
      ) : null}
    </RequiresProject>
  );
}

export default BcfPage;
