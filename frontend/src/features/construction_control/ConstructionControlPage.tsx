// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Construction Control (QA/QC) page.
//
// One module surfacing the five pillars of the construction-control engine as
// tabs over the active project: acceptance criteria + inspections, material
// records + lab tests, as-built records, hold / witness gating, and the
// handover / acceptance package. The active project comes from the global
// header switcher (useProjectContextStore), the same way Closeout and the
// Asset Register pick their project; RequiresProject shows a single consistent
// empty state when no project is selected.

import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import {
  ClipboardCheck,
  Boxes,
  Ruler,
  ShieldAlert,
  PackageCheck,
} from 'lucide-react';
import { TabBar, tabIds, ModuleGuideButton, type TabBarTab } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { constructionControlGuide } from './construction_controlGuide';
import { AcceptanceInspectionsSection } from './sections/AcceptanceInspectionsSection';
import { MaterialsLabsSection } from './sections/MaterialsLabsSection';
import { AsBuiltSection } from './sections/AsBuiltSection';
import { HoldWitnessSection } from './sections/HoldWitnessSection';
import { HandoverSection } from './sections/HandoverSection';
import {
  DEFAULT_CONSTRUCTION_CONTROL_TAB,
  isConstructionControlTab,
  type ConstructionControlTab as PillarTab,
} from './constructionControlTabs';

const TAB_PANEL = tabIds('construction-control');

export function ConstructionControlPage() {
  const { t } = useTranslation();
  const activeProjectId = useActiveProjectId();
  const [searchParams, setSearchParams] = useSearchParams();

  // The active tab lives in ?tab=, so a case step or a shared link can open
  // the Handover tab directly (/projects/:projectId/construction-control
  // ?tab=handover) and a reload keeps the tab. Switches write it back,
  // replacing rather than pushing, and keep any other params.
  const rawTab = searchParams.get('tab');
  const activeTab: PillarTab = isConstructionControlTab(rawTab) ? rawTab : DEFAULT_CONSTRUCTION_CONTROL_TAB;
  const setActiveTab = (next: PillarTab) =>
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.set('tab', next);
        return params;
      },
      { replace: true },
    );

  const tabs: TabBarTab<PillarTab>[] = [
    {
      id: 'inspections',
      label: t('construction_control.tab.inspections', { defaultValue: 'Inspections' }),
      icon: <ClipboardCheck className="h-4 w-4" />,
    },
    {
      id: 'materials',
      label: t('construction_control.tab.materials', { defaultValue: 'Materials & Tests' }),
      icon: <Boxes className="h-4 w-4" />,
    },
    {
      id: 'asbuilt',
      label: t('construction_control.tab.asbuilt', { defaultValue: 'As-Built' }),
      icon: <Ruler className="h-4 w-4" />,
    },
    {
      id: 'gates',
      label: t('construction_control.tab.gates', { defaultValue: 'Hold Points' }),
      icon: <ShieldAlert className="h-4 w-4" />,
    },
    {
      id: 'handover',
      label: t('construction_control.tab.handover', { defaultValue: 'Handover' }),
      icon: <PackageCheck className="h-4 w-4" />,
    },
  ];

  return (
    // Full-width frame to match every other module surface (the app shell
    // already provides the gutter and top padding, see AppLayout <main>).
    <div className="w-full">
      <PageHeader
        srTitle={t('construction_control.title', { defaultValue: 'Construction Control' })}
        subtitle={t('construction_control.subtitle', {
          defaultValue:
            'Quality assurance and control: acceptance criteria, inspections, material passports, as-built records, hold points and the acceptance handover package.',
        })}
        actions={<ModuleGuideButton content={constructionControlGuide} />}
      />

      <RequiresProject
        emptyHint={t('construction_control.select_project_hint', {
          defaultValue:
            'Pick a project from the header to manage its acceptance criteria, inspections and acceptance evidence.',
        })}
      >
        <div className="mt-4">
          <TabBar
            tabs={tabs}
            activeId={activeTab}
            onChange={setActiveTab}
            ariaLabel={t('construction_control.tabs_aria', {
              defaultValue: 'Construction control sections',
            })}
            idPrefix="construction-control"
            testIdPrefix="cc"
          />

          <div
            role="tabpanel"
            id={TAB_PANEL.panelId(activeTab)}
            aria-labelledby={TAB_PANEL.tabId(activeTab)}
            className="mt-5"
          >
            {/* RequiresProject guarantees a project id here, but keep the guard
                so each section never has to special-case a null id. */}
            {activeProjectId ? (
              <>
                {activeTab === 'inspections' && (
                  <AcceptanceInspectionsSection projectId={activeProjectId} />
                )}
                {activeTab === 'materials' && <MaterialsLabsSection projectId={activeProjectId} />}
                {activeTab === 'asbuilt' && <AsBuiltSection projectId={activeProjectId} />}
                {activeTab === 'gates' && <HoldWitnessSection projectId={activeProjectId} />}
                {activeTab === 'handover' && <HandoverSection projectId={activeProjectId} />}
              </>
            ) : null}
          </div>
        </div>
      </RequiresProject>
    </div>
  );
}

export default ConstructionControlPage;
