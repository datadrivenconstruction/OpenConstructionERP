// Design module (ERP side of the design editor link).
import { lazy } from 'react';
import { Boxes, Calculator, ClipboardCheck, DraftingCompass, LayoutList, PencilRuler } from 'lucide-react';
import type { ModuleManifest } from '../_types';
import { CONSENT_KEY } from './data/webEditor';

const OverviewPage = lazy(() => import('./OverviewPage'));
const StartPage = lazy(() => import('./StartPage'));
const BriefPage = lazy(() => import('./BriefPage'));
const RevisionsPage = lazy(() => import('./RevisionsPage'));
const AcceptancePage = lazy(() => import('./AcceptancePage'));
const EstimatePage = lazy(() => import('./EstimatePage'));
const EditorLinkPage = lazy(() => import('./EditorLinkPage'));
const EditorWorkspace = lazy(() => import('./EditorWorkspace'));

export const manifest: ModuleManifest = {
  id: 'design',
  name: 'design.title',
  description: 'design.module_description',
  version: '0.1.0',
  icon: DraftingCompass,
  category: 'planning',
  // Its own top-level menu section for everyone; a person hides it through the menu editor.
  defaultEnabled: true,
  // Pages it writes into and links to (activities, tender packages); switching Design on switches them on.
  depends: ['schedule', 'tendering'],
  routes: [{ path: '/design/overview', title: 'design.overview.title', component: OverviewPage },
    { path: '/design/start', title: 'design.start.title', component: StartPage },
    { path: '/design/brief', title: 'design.brief.title', component: BriefPage },
    { path: '/design/revisions', title: 'design.revisions.title', component: RevisionsPage },
    { path: '/design/acceptance', title: 'design.acceptance.title', component: AcceptancePage },
    { path: '/design/estimate', title: 'design.estimate.title', component: EstimatePage },
    { path: '/design/editor', title: 'design.editor.title', component: EditorWorkspace },
    { path: '/design/editor/desktop', title: 'design.editor.desktop_title', component: EditorLinkPage },
  ],
  // Own sidebar section "Design" (grp_design, core patch 0008), in the order a project is designed:
  // start and overview, the editor, then brief, revisions, acceptance and the estimate they feed.
  navItems: [
    { labelKey: 'design.overview.nav', to: '/design/overview', icon: LayoutList, group: 'grp_design' },
    { labelKey: 'design.editor.nav', to: '/design/editor', icon: PencilRuler, group: 'grp_design' },
    { labelKey: 'design.brief.title', to: '/design/brief', icon: DraftingCompass, group: 'grp_design' },
    { labelKey: 'design.revisions.nav', to: '/design/revisions', icon: Boxes, group: 'grp_design' },
    { labelKey: 'design.acceptance.nav', to: '/design/acceptance', icon: ClipboardCheck, group: 'grp_design' },
    { labelKey: 'design.estimate.nav', to: '/design/estimate', icon: Calculator, group: 'grp_design' },
  ],
};

// Someone who said yes to the design offer gets the editor loaded in idle time at start-up; nobody else downloads it.
try {
  if (typeof window !== 'undefined' && window.localStorage.getItem(CONSENT_KEY) === 'yes') {
    void import('./editorPayload').then((m) => m.startBackgroundLoad('yes'));
  }
} catch { /* storage blocked: no background load */ }
