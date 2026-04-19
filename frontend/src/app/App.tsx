import { Suspense, lazy, useState, useCallback, useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '@/features/auth';
import { ProjectsPage, CreateProjectPage, ProjectDetailPage } from '@/features/projects';
import { BOQListPage, CreateBOQPage, TemplatesPage } from '@/features/boq';
import { CostsPage, ImportDatabasePage } from '@/features/costs';
import { OnboardingWizard } from '@/features/onboarding';
import { AssembliesPage, AssemblyEditorPage, CreateAssemblyPage } from '@/features/assemblies';
import { ValidationPage } from '@/features/validation';
import { QuantitiesPage } from '@/features/quantities';
import { ModulesPage } from '@/features/modules';
import { useModuleRouteElements } from '@/modules/ModuleRoutes';
import { SettingsPage } from '@/features/settings';
import { DatabaseSetupPage } from '@/features/setup';
import { IntegrationsPage } from '@/features/integrations';
import { AboutPage } from '@/features/about/AboutPage';
import { QuickEstimatePage } from '@/features/ai';
import { Logo, ShortcutsDialog, CommandPalette, ToastContainer, ErrorBoundary, NotFoundPage } from '@/shared/ui';
import GlobalSearchModal from '@/features/search/GlobalSearchModal';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { FloatingQueuePanel } from './layout/FloatingQueuePanel';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { ddcVerifyIntegrity } from '@/shared/lib/ddc-integrity';
import { useKeyboardShortcuts } from '@/shared/hooks/useKeyboardShortcuts';
import { useTranslation } from 'react-i18next';
import { getLanguageByCode } from './i18n';
import { initErrorLogger } from '@/shared/lib/errorLogger';

// Lazy-loaded heavy pages — code-split into separate chunks
const BOQEditorPage = lazy(() =>
  import('@/features/boq/BOQEditorPage').then((m) => ({ default: m.BOQEditorPage }))
);
const CostModelPage = lazy(() =>
  import('@/features/costmodel/CostModelPage').then((m) => ({ default: m.CostModelPage }))
);
const SchedulePage = lazy(() =>
  import('@/features/schedule/SchedulePage').then((m) => ({ default: m.SchedulePage }))
);
const TakeoffPage = lazy(() =>
  import('@/features/takeoff/TakeoffPage').then((m) => ({ default: m.TakeoffPage }))
);
const CadDataExplorerPage = lazy(() =>
  import('@/features/cad-explorer/CadDataExplorerPage').then((m) => ({ default: m.CadDataExplorerPage }))
);
const TenderingPage = lazy(() =>
  import('@/features/tendering/TenderingPage').then((m) => ({ default: m.TenderingPage }))
);
const ReportsPage = lazy(() =>
  import('@/features/reports/ReportsPage').then((m) => ({ default: m.ReportsPage }))
);
const CatalogPage = lazy(() =>
  import('@/features/catalog/CatalogPage').then((m) => ({ default: m.CatalogPage }))
);
const AdvisorPage = lazy(() =>
  import('@/features/ai/AdvisorPage').then((m) => ({ default: m.AdvisorPage }))
);
const ERPChatPage = lazy(() =>
  import('@/features/erp-chat/full-page/ChatFullPage')
);
const ChangeOrdersPage = lazy(() =>
  import('@/features/changeorders/ChangeOrdersPage').then((m) => ({ default: m.ChangeOrdersPage }))
);
const AnalyticsPage = lazy(() =>
  import('@/features/analytics/AnalyticsPage').then((m) => ({ default: m.AnalyticsPage }))
);
const RiskRegisterPage = lazy(() =>
  import('@/features/risk/RiskRegisterPage').then((m) => ({ default: m.RiskRegisterPage }))
);
const DocumentsPage = lazy(() =>
  import('@/features/documents/DocumentsPage').then((m) => ({ default: m.DocumentsPage }))
);
const PhotoGalleryPage = lazy(() =>
  import('@/features/documents/PhotoGalleryPage').then((m) => ({ default: m.PhotoGalleryPage }))
);
// RequirementsPage merged into /bim/rules — route removed, redirect added
// const RequirementsPage = lazy(() =>
//   import('@/features/requirements/RequirementsPage').then((m) => ({ default: m.RequirementsPage }))
// );
const MarkupsPage = lazy(() =>
  import('@/features/markups/MarkupsPage').then((m) => ({ default: m.MarkupsPage }))
);
const PunchListPage = lazy(() =>
  import('@/features/punchlist/PunchListPage').then((m) => ({ default: m.PunchListPage }))
);
const FieldReportsPage = lazy(() =>
  import('@/features/fieldreports/FieldReportsPage').then((m) => ({ default: m.FieldReportsPage }))
);
const FinancePage = lazy(() =>
  import('@/features/finance/FinancePage').then((m) => ({ default: m.FinancePage }))
);
const ProcurementPage = lazy(() =>
  import('@/features/procurement/ProcurementPage').then((m) => ({ default: m.ProcurementPage }))
);
const SafetyPage = lazy(() =>
  import('@/features/safety/SafetyPage').then((m) => ({ default: m.SafetyPage }))
);
const ContactsPage = lazy(() =>
  import('@/features/contacts/ContactsPage').then((m) => ({ default: m.ContactsPage }))
);
const TasksPage = lazy(() =>
  import('@/features/tasks/TasksPage').then((m) => ({ default: m.TasksPage }))
);
const RFIPage = lazy(() =>
  import('@/features/rfi/RFIPage').then((m) => ({ default: m.RFIPage }))
);
const SubmittalsPage = lazy(() =>
  import('@/features/submittals/SubmittalsPage').then((m) => ({ default: m.SubmittalsPage }))
);
const CorrespondencePage = lazy(() =>
  import('@/features/correspondence/CorrespondencePage').then((m) => ({ default: m.CorrespondencePage }))
);
const CDEPage = lazy(() =>
  import('@/features/cde/CDEPage').then((m) => ({ default: m.CDEPage }))
);
const TransmittalsPage = lazy(() =>
  import('@/features/transmittals/TransmittalsPage').then((m) => ({ default: m.TransmittalsPage }))
);
const MeetingsPage = lazy(() =>
  import('@/features/meetings/MeetingsPage').then((m) => ({ default: m.MeetingsPage }))
);
const InspectionsPage = lazy(() =>
  import('@/features/inspections/InspectionsPage').then((m) => ({ default: m.InspectionsPage }))
);
const NCRPage = lazy(() =>
  import('@/features/ncr/NCRPage').then((m) => ({ default: m.NCRPage }))
);
const ReportingPage = lazy(() =>
  import('@/features/reporting/ReportingPage').then((m) => ({ default: m.ReportingPage }))
);
const DwgTakeoffPage = lazy(() =>
  import('@/features/dwg-takeoff/DwgTakeoffPage').then((m) => ({ default: m.DwgTakeoffPage }))
);
const BIMPage = lazy(() =>
  import('@/features/bim/BIMPage').then((m) => ({ default: m.BIMPage }))
);
const BIMQuantityRulesPage = lazy(() =>
  import('@/features/bim/BIMQuantityRulesPage').then((m) => ({ default: m.BIMQuantityRulesPage }))
);
const UserManagementPage = lazy(() =>
  import('@/features/users/UserManagementPage').then((m) => ({ default: m.UserManagementPage }))
);
const ArchitectureMapPage = lazy(() =>
  import('@/features/architecture/ArchitectureMapPage').then((m) => ({ default: m.ArchitectureMapPage }))
);
const ProjectIntelligencePage = lazy(() =>
  import('@/features/project-intelligence/ProjectIntelligencePage').then((m) => ({ default: m.ProjectIntelligencePage }))
);

function LoadingScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-secondary">
      <div className="flex flex-col items-center gap-3 animate-fade-in">
        <Logo size="lg" animate />
        <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-secondary">
          <div className="h-full w-8 animate-shimmer rounded-full bg-oe-blue opacity-60" />
        </div>
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();
  if (!isAuthenticated) {
    // Preserve intended destination so the user lands where they wanted
    // after signing in (BUG-047). Avoids the "bookmarked /boq then sent
    // back to /" UX papercut.
    const next = `${location.pathname}${location.search}`;
    const qs = next && next !== '/' ? `?next=${encodeURIComponent(next)}` : '';
    return <Navigate to={`/login${qs}`} replace />;
  }
  return <>{children}</>;
}

function P({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppLayout title={title}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </AppLayout>
    </RequireAuth>
  );
}

/** Mounts global keyboard shortcuts, the shortcuts help dialog, and the command palette. */
function GlobalShortcuts() {
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  const handleToggleShortcuts = useCallback(() => {
    setShortcutsOpen((prev) => !prev);
  }, []);

  // The `/` shortcut for search is already handled by Header's own keydown
  // listener, so we pass a no-op here to avoid duplicate triggers.
  const noop = useCallback(() => {}, []);

  useKeyboardShortcuts({
    onOpenSearch: noop,
    onToggleShortcutsDialog: handleToggleShortcuts,
  });

  // Ctrl+K / Cmd+K to open command palette
  // / to open command palette (when not typing)
  // Note: Ctrl+N / Ctrl+Shift+N are reserved by the browser (new window/incognito)
  // and cannot be intercepted reliably — use the `n p` two-key sequence instead.
  // Ctrl+Shift+V is reserved for Excel paste in BOQ Editor — don't bind it globally.

  const openGlobalSearch = useGlobalSearchStore((s) => s.openModal);
  const toggleGlobalSearch = useGlobalSearchStore((s) => s.toggleModal);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      const tag = (e.target as HTMLElement)?.tagName;
      const isTextField =
        tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

      // Cmd/Ctrl+Shift+K → semantic search modal (cross-module vector search).
      // Bound BEFORE the plain Cmd+K branch so the shift modifier short-
      // circuits the navigation palette.  Works even from text fields so
      // estimators can trigger semantic search while editing a BOQ row.
      if (mod && e.shiftKey && (e.key === 'K' || e.key === 'k')) {
        e.preventDefault();
        toggleGlobalSearch();
        return;
      }

      if (isTextField) return;

      if (mod && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
      if (e.key === '/' && !mod) {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [toggleGlobalSearch, openGlobalSearch]);

  return (
    <>
      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <GlobalSearchModal />
    </>
  );
}

// Run once at module load — synchronous, before any render
useAuthStore.getState().loadFromStorage();
useThemeStore.getState().init();

// Initialize the anonymized error logger (global handlers for unhandled errors)
initErrorLogger();

/** Keeps <html dir="..."> and lang attribute in sync with the active i18n language. */
function useDocumentDirection() {
  const { i18n } = useTranslation();

  // Set dir immediately on mount (not just on language change)
  useEffect(() => {
    const lang = getLanguageByCode(i18n.language);
    const dir = (lang && 'dir' in lang && lang.dir === 'rtl') ? 'rtl' : 'ltr';
    document.documentElement.dir = dir;
    document.documentElement.lang = i18n.language;
  }, [i18n.language]);

  // Also listen for runtime language changes
  useEffect(() => {
    const handler = (lng: string) => {
      const lang = getLanguageByCode(lng);
      const dir = (lang && 'dir' in lang && lang.dir === 'rtl') ? 'rtl' : 'ltr';
      document.documentElement.dir = dir;
      document.documentElement.lang = lng;
    };
    i18n.on('languageChanged', handler);
    return () => { i18n.off('languageChanged', handler); };
  }, [i18n]);
}

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  useDocumentDirection();

  // DDC-CWICR-OE integrity verification
  if (typeof window !== 'undefined') {
    (window as any).__ddc_oe = ddcVerifyIntegrity();
  }

  // Dynamic routes from the module registry (lazy-loaded)
  const moduleRoutes = useModuleRouteElements({ Wrapper: P });

  return (
    <Suspense fallback={<LoadingScreen />}>
      {isAuthenticated && <GlobalShortcuts />}
      <Routes>
        {/* Auth — public */}
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" replace /> : <RegisterPage />} />
        <Route path="/forgot-password" element={isAuthenticated ? <Navigate to="/" replace /> : <ForgotPasswordPage />} />

        {/* Onboarding — full-screen, no layout */}
        <Route path="/onboarding" element={
          <RequireAuth><OnboardingWizard /></RequireAuth>
        } />

        {/* App — all protected, all real pages */}
        <Route path="/" element={<P title="Dashboard"><DashboardPage /></P>} />

        <Route path="/ai-estimate" element={<P title="AI Quick Estimate"><QuickEstimatePage /></P>} />
        <Route path="/advisor" element={<P title="AI Cost Advisor"><AdvisorPage /></P>} />
        <Route path="/chat" element={<P title="AI Chat"><ERPChatPage /></P>} />
        <Route path="/cad-takeoff" element={<Navigate to="/data-explorer" replace />} />
        <Route path="/data-explorer" element={<P title="Data Explorer"><CadDataExplorerPage /></P>} />
        <Route path="/bim" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/bim/rules" element={<P title="BIM Rules"><BIMQuantityRulesPage /></P>} />
        <Route path="/bim/:modelId" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/projects/:projectId/bim" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/projects/:projectId/bim/:modelId" element={<P title="BIM Viewer"><BIMPage /></P>} />

        <Route path="/projects" element={<P title="Projects"><ProjectsPage /></P>} />
        <Route path="/projects/new" element={<P title="New Project"><CreateProjectPage /></P>} />
        <Route path="/projects/:projectId" element={<P title="Project"><ProjectDetailPage /></P>} />
        <Route path="/projects/:projectId/boq/new" element={<P title="New BOQ"><CreateBOQPage /></P>} />

        <Route path="/boq" element={<P title="Bill of Quantities"><BOQListPage /></P>} />
        <Route path="/boq/:boqId" element={<P title="BOQ Editor"><BOQEditorPage /></P>} />
        <Route path="/templates" element={<P title="BOQ Templates"><TemplatesPage /></P>} />

        <Route path="/costs" element={<P title="Cost Database"><CostsPage /></P>} />
        <Route path="/costs/import" element={<P title="Import Cost Database"><ImportDatabasePage /></P>} />

        <Route path="/catalog" element={<P title="Resource Catalog"><CatalogPage /></P>} />

        <Route path="/assemblies" element={<P title="Assemblies"><AssembliesPage /></P>} />
        <Route path="/assemblies/new" element={<P title="New Assembly"><CreateAssemblyPage /></P>} />
        <Route path="/assemblies/:assemblyId" element={<P title="Assembly Editor"><AssemblyEditorPage /></P>} />

        <Route path="/validation" element={<P title="Validation"><ValidationPage /></P>} />

        <Route path="/quantities" element={<P title="Quantity Takeoff"><QuantitiesPage /></P>} />
        <Route path="/takeoff" element={<P title="PDF Takeoff"><TakeoffPage /></P>} />
        <Route path="/dwg-takeoff" element={<P title="DWG Takeoff"><DwgTakeoffPage /></P>} />

        <Route path="/schedule" element={<P title="4D Schedule"><SchedulePage /></P>} />

        <Route path="/5d" element={<P title="5D Cost Model"><CostModelPage /></P>} />

        <Route path="/analytics" element={<P title="Analytics"><AnalyticsPage /></P>} />

        <Route path="/reports" element={<P title="Reports"><ReportsPage /></P>} />
        <Route path="/reporting" element={<P title="Reporting Dashboards"><ReportingPage /></P>} />

        <Route path="/tendering" element={<P title="Tendering"><TenderingPage /></P>} />

        <Route path="/changeorders" element={<P title="Change Orders"><ChangeOrdersPage /></P>} />
        <Route path="/documents" element={<P title="Documents"><DocumentsPage /></P>} />
        <Route path="/photos" element={<P title="Project Photos"><PhotoGalleryPage /></P>} />

        <Route path="/risks" element={<P title="Risk Register"><RiskRegisterPage /></P>} />

        {/* Requirements merged into BIM Rules page */}
        <Route path="/requirements" element={<Navigate to="/bim/rules" replace />} />

        <Route path="/markups" element={<P title="Markups"><MarkupsPage /></P>} />
        <Route path="/punchlist" element={<P title="Punch List"><PunchListPage /></P>} />
        <Route path="/field-reports" element={<P title="Field Reports"><FieldReportsPage /></P>} />

        <Route path="/finance" element={<P title="Finance"><FinancePage /></P>} />
        <Route path="/projects/:projectId/finance" element={<P title="Finance"><FinancePage /></P>} />

        <Route path="/procurement" element={<P title="Procurement"><ProcurementPage /></P>} />
        <Route path="/projects/:projectId/procurement" element={<P title="Procurement"><ProcurementPage /></P>} />

        <Route path="/safety" element={<P title="Safety"><SafetyPage /></P>} />
        <Route path="/projects/:projectId/safety" element={<P title="Safety"><SafetyPage /></P>} />

        <Route path="/contacts" element={<P title="Contacts"><ContactsPage /></P>} />
        <Route path="/projects/:projectId/tasks" element={<P title="Tasks"><TasksPage /></P>} />
        <Route path="/tasks" element={<P title="Tasks"><TasksPage /></P>} />
        <Route path="/projects/:projectId/rfi" element={<P title="RFI"><RFIPage /></P>} />
        <Route path="/rfi" element={<P title="RFI"><RFIPage /></P>} />
        <Route path="/projects/:projectId/submittals" element={<P title="Submittals"><SubmittalsPage /></P>} />
        <Route path="/submittals" element={<P title="Submittals"><SubmittalsPage /></P>} />
        <Route path="/projects/:projectId/correspondence" element={<P title="Correspondence"><CorrespondencePage /></P>} />
        <Route path="/correspondence" element={<P title="Correspondence"><CorrespondencePage /></P>} />
        <Route path="/projects/:projectId/cde" element={<P title="CDE"><CDEPage /></P>} />
        <Route path="/cde" element={<P title="CDE"><CDEPage /></P>} />
        <Route path="/projects/:projectId/transmittals" element={<P title="Transmittals"><TransmittalsPage /></P>} />
        <Route path="/transmittals" element={<P title="Transmittals"><TransmittalsPage /></P>} />
        <Route path="/projects/:projectId/meetings" element={<P title="Meetings"><MeetingsPage /></P>} />
        <Route path="/meetings" element={<P title="Meetings"><MeetingsPage /></P>} />
        <Route path="/projects/:projectId/inspections" element={<P title="Inspections"><InspectionsPage /></P>} />
        <Route path="/inspections" element={<P title="Inspections"><InspectionsPage /></P>} />
        <Route path="/projects/:projectId/ncr" element={<P title="NCR"><NCRPage /></P>} />
        <Route path="/ncr" element={<P title="NCR"><NCRPage /></P>} />

        <Route path="/users" element={<P title="User Management"><UserManagementPage /></P>} />
        <Route path="/modules" element={<P title="Modules"><ModulesPage /></P>} />

        <Route path="/setup/databases" element={<P title="Databases & Resources"><DatabaseSetupPage /></P>} />
        <Route path="/settings" element={<P title="Settings"><SettingsPage /></P>} />
        <Route path="/integrations" element={<P title="Integrations"><IntegrationsPage /></P>} />
        <Route path="/about" element={<P title="About"><AboutPage /></P>} />
        <Route path="/project-intelligence" element={<P title="Project Intelligence"><ProjectIntelligencePage /></P>} />
        <Route path="/architecture" element={<P title="Architecture Map"><ArchitectureMapPage /></P>} />

        {/* Convenience route aliases — redirect to canonical paths */}
        <Route path="/dashboard" element={<Navigate to="/" replace />} />
        <Route path="/change-orders" element={<Navigate to="/changeorders" replace />} />
        <Route path="/punch-list" element={<Navigate to="/punchlist" replace />} />
        <Route path="/variations" element={<Navigate to="/changeorders" replace />} />
        <Route path="/estimates" element={<Navigate to="/boq" replace />} />
        <Route path="/profile" element={<Navigate to="/settings" replace />} />
        <Route path="/notifications" element={<Navigate to="/settings" replace />} />

        {/* Plugin module routes — lazy-loaded */}
        {moduleRoutes}

        {/* 404 — catch-all for unknown routes */}
        <Route path="*" element={isAuthenticated ? <P title="Not Found"><NotFoundPage /></P> : <Navigate to="/login" replace />} />
      </Routes>
      <ToastContainer />
      <FloatingQueuePanel />
      {/* DDC-CWICR-OE */}
      <span aria-hidden="true" style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}>
        {'\u200B\u200C\u200D\u200B\u200C\u200D\u200B'}
        DataDrivenConstruction·CWICR·OpenConstructionERP·2026
      </span>
    </Suspense>
  );
}
