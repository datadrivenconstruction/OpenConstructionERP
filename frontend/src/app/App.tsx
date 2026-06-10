import { Suspense, lazy, useState, useCallback, useEffect, useLayoutEffect, useContext, createContext } from 'react';
import { Routes, Route, Navigate, Outlet, useLocation, useParams } from 'react-router-dom';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '@/features/auth';
import { ProjectsPage, CreateProjectPage, ProjectDetailPage, ProjectSettingsPage } from '@/features/projects';
// Import the lightweight BOQ pages from their source modules directly,
// NOT via the `@/features/boq` barrel.  The barrel re-exports
// `BOQEditorPage`, which statically pulls `BOQGrid` → `ag-grid-react` +
// `ag-grid-community` (~900 KB).  An eager barrel import evaluates the
// whole barrel graph, so ag-grid landed in the initial `index` chunk and
// defeated the `lazy(() => import('@/features/boq/BOQEditorPage'))` below
// (V320-PERF-01).  Deep-importing the light pages severs that eager edge
// so ag-grid stays in the lazy BOQ-editor chunk.
import { BOQListPage } from '@/features/boq/BOQListPage';
import { CreateBOQPage } from '@/features/boq/CreateBOQPage';
import { TemplatesPage } from '@/features/boq/TemplatesPage';
import { syncCustomUnitsFromServer } from '@/features/boq/boqHelpers';
import { NlRuleBuilderPanel } from '@/features/compliance';
import { useModuleRouteElements } from '@/modules/ModuleRoutes';
import { DatabaseSetupPage } from '@/features/setup';
import { Logo, ShortcutsDialog, CommandPalette, ToastContainer, BackgroundInstallBanner, ErrorBoundary, NotFoundPage, ProductTour, OfflineBanner, PWAInstallPrompt } from '@/shared/ui';
import { AdminOnly } from '@/shared/auth/AdminOnly';
import GlobalSearchModal from '@/features/search/GlobalSearchModal';
import { useGlobalSearchStore } from '@/stores/useGlobalSearchStore';
import { FloatingQueuePanel } from './layout/FloatingQueuePanel';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { ddcVerifyIntegrity, ddcInjectMeta, DDC_ORIGIN } from '@/shared/lib/ddc-integrity';
import { NavigationProgress } from '@/shared/lib/navigationProgress';
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
const PointCloudPage = lazy(() =>
  import('@/features/pointcloud/PointCloudPage').then((m) => ({ default: m.PointCloudPage }))
);
const MatchElementsPage = lazy(() =>
  import('@/features/match-elements/MatchElementsPage').then((m) => ({ default: m.MatchElementsPage }))
);
const NotificationsPage = lazy(() =>
  import('@/features/notifications/NotificationsPage').then((m) => ({ default: m.NotificationsPage }))
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
const ERPChatAdminStatsPage = lazy(() =>
  import('@/features/erp-chat/AdminStatsPage')
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
// DocumentsPage merged into the unified File Manager — /documents now
// redirects to /files. Keeping the source file on disk for cleanup in a
// later release; nothing imports DocumentsPage today.
const PhotoGalleryPage = lazy(() =>
  import('@/features/documents/PhotoGalleryPage').then((m) => ({ default: m.PhotoGalleryPage }))
);
// RequirementsPage merged into /bim/rules — route removed, redirect added
// const RequirementsPage = lazy(() =>
//   import('@/features/requirements/RequirementsPage').then((m) => ({ default: m.RequirementsPage }))
// );
// Wave 4 / T13 — ISO 19650 EIR (Employer Information Requirements) matrix.
const RequirementsMatrixPage = lazy(() =>
  import('@/features/requirements/RequirementsMatrixPage').then((m) => ({
    default: m.RequirementsMatrixPage,
  })),
);
const MarkupsPage = lazy(() =>
  import('@/features/markups/MarkupsPage').then((m) => ({ default: m.MarkupsPage }))
);
const PdfComparePage = lazy(() =>
  import('@/features/markups/PdfCompare').then((m) => ({ default: m.PdfComparePage }))
);
const PunchListPage = lazy(() =>
  import('@/features/punchlist/PunchListPage').then((m) => ({ default: m.PunchListPage }))
);
const CloseoutPage = lazy(() => import('@/features/closeout/CloseoutPage'));
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
const RFIDetailPage = lazy(() =>
  import('@/features/rfi/RFIDetailPage').then((m) => ({ default: m.RFIDetailPage }))
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
const MoCPage = lazy(() =>
  import('@/features/moc/MoCPage').then((m) => ({ default: m.MoCPage }))
);
const ReportingPage = lazy(() =>
  import('@/features/reporting/ReportingPage').then((m) => ({ default: m.ReportingPage }))
);
const DwgTakeoffPage = lazy(() =>
  import('@/features/dwg-takeoff/DwgTakeoffPage').then((m) => ({ default: m.DwgTakeoffPage }))
);
const AssetsPage = lazy(() =>
  import('@/features/bim/AssetsPage').then((m) => ({ default: m.AssetsPage }))
);
const BIMPage = lazy(() =>
  import('@/features/bim/BIMPage').then((m) => ({ default: m.BIMPage }))
);
const BIMQuantityRulesPage = lazy(() =>
  import('@/features/bim/BIMQuantityRulesPage').then((m) => ({ default: m.BIMQuantityRulesPage }))
);
const ClashDetectionPage = lazy(() =>
  import('@/features/clash/ClashDetectionPage').then((m) => ({ default: m.ClashDetectionPage }))
);
const ClashProfileManager = lazy(() => import('@/features/clash/ClashProfileManager'));
const UserManagementPage = lazy(() =>
  import('@/features/users/UserManagementPage').then((m) => ({ default: m.UserManagementPage }))
);
// Admin: read-only audit-log timeline (`audit.view` Manager+).
const AuditLogPage = lazy(() =>
  import('@/features/admin/AuditLogPage').then((m) => ({ default: m.AuditLogPage }))
);
// (PermissionsMatrixPage now mounts inside GovernancePage — see below.)
// Admin: Epic B / B11 — outbound notification webhook targets.
const WebhookTargetsPage = lazy(() =>
  import('@/features/admin/WebhookTargetsPage').then((m) => ({
    default: m.WebhookTargetsPage,
  })),
);
// (ApprovalRoutesPage now mounts inside GovernancePage — see below.)
// Governance — one module merging Permissions + Approval Routes +
// Validation Rules behind /governance with /modules-style top tabs.
// The three old standalone routes redirect here, preserving the tab.
const GovernancePage = lazy(() =>
  import('@/features/governance').then((m) => ({
    default: m.GovernancePage,
  })),
);
const ArchitectureMapPage = lazy(() =>
  import('@/features/architecture/ArchitectureMapPage').then((m) => ({ default: m.ArchitectureMapPage }))
);
const ProjectIntelligencePage = lazy(() =>
  import('@/features/project-intelligence/ProjectIntelligencePage').then((m) => ({ default: m.ProjectIntelligencePage }))
);
const FileManagerPage = lazy(() =>
  import('@/features/file-manager/FileManagerPage').then((m) => ({ default: m.FileManagerPage }))
);
const TrashPage = lazy(() =>
  import('@/features/file-trash/TrashPage').then((m) => ({ default: m.TrashPage }))
);
const GlobalSearchPage = lazy(() =>
  import('@/features/file-distribution').then((m) => ({ default: m.GlobalSearchPage }))
);
const TransmittalLogPage = lazy(() =>
  import('@/features/file-transmittals/TransmittalLogPage').then((m) => ({ default: m.TransmittalLogPage }))
);
const SharePage = lazy(() =>
  import('@/features/file-manager/SharePage').then((m) => ({ default: m.SharePage }))
);
const BuyerPortalPage = lazy(() =>
  import('@/features/buyer-portal/BuyerPortalPage').then((m) => ({
    default: m.BuyerPortalPage,
  }))
);
// Field-worker mobile shell + PIN-redemption auth. See
// docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md. Lazy-loaded in its
// own chunk so the desktop bundle is unaffected.
const FieldShellPage = lazy(() =>
  import('@/features/field/FieldShellPage').then((m) => ({
    default: m.FieldShellPage,
  }))
);
const FieldAuthPage = lazy(() =>
  import('@/features/field/FieldAuthPage').then((m) => ({
    default: m.FieldAuthPage,
  }))
);
const SnapshotsPage = lazy(() =>
  import('@/features/dashboards').then((m) => ({ default: m.SnapshotsPage }))
);
// EAC-3.1 scaffolding (RFC 35 §7) — block primitives preview. Dev-only route.
const EacDemoPage = lazy(() =>
  import('@/features/eac/pages/EacDemoPage').then((m) => ({ default: m.EacDemoPage }))
);
// EAC-3.2 — visual block editor canvas (xyflow). Per-ruleset editing UI.
const EACBlockEditorPage = lazy(() =>
  import('@/features/eac/EACBlockEditorPage').then((m) => ({ default: m.EACBlockEditorPage }))
);
// Styles Lab — internal design exploration page (modern style variants).
const StylesLabPage = lazy(() =>
  import('@/features/styles-lab/StylesLabPage').then((m) => ({ default: m.StylesLabPage }))
);

// 18-Modules Wave — Field Operations / Commercial / Schedule & Quality.
// Each module is its own lazy chunk so the boot bundle stays small.
const ServicePage = lazy(() =>
  import('@/features/service').then((m) => ({ default: m.ServicePage }))
);
const SubcontractorsPage = lazy(() =>
  import('@/features/subcontractors').then((m) => ({ default: m.SubcontractorsPage }))
);
const EquipmentPage = lazy(() =>
  import('@/features/equipment').then((m) => ({ default: m.EquipmentPage }))
);
const PayrollPage = lazy(() => import('@/features/payroll/PayrollPage'));
const PortalPage = lazy(() =>
  import('@/features/portal').then((m) => ({ default: m.PortalPage }))
);
const PortalPaymentsPage = lazy(() =>
  import('@/features/portal').then((m) => ({ default: m.PortalPaymentsPage }))
);
const ResourcesPage = lazy(() =>
  import('@/features/resources').then((m) => ({ default: m.ResourcesPage }))
);
const CapacityPlanningPage = lazy(() =>
  import('@/features/portfolio/CapacityPlanningPage').then((m) => ({
    default: m.CapacityPlanningPage,
  }))
);
const ResourceLevelingPage = lazy(() =>
  import('@/features/portfolio/ResourceLevelingPage').then((m) => ({
    default: m.ResourceLevelingPage,
  }))
);
const ContractsPage = lazy(() =>
  import('@/features/contracts').then((m) => ({ default: m.ContractsPage }))
);
const ProgressClaimDetailPage = lazy(() =>
  import('@/features/contracts').then((m) => ({ default: m.ProgressClaimDetailPage }))
);
const CRMPage = lazy(() =>
  import('@/features/crm').then((m) => ({ default: m.CRMPage }))
);
const CarbonPage = lazy(() =>
  import('@/features/carbon').then((m) => ({ default: m.CarbonPage }))
);
const PropertyDevPage = lazy(() =>
  import('@/features/property-dev').then((m) => ({ default: m.PropertyDevPage }))
);
const PropertyDevInventoryMapPage = lazy(() =>
  import('@/features/property-dev').then((m) => ({ default: m.InventoryMapPage }))
);
const AccommodationListPage = lazy(() =>
  import('@/features/accommodation').then((m) => ({
    default: m.AccommodationListPage,
  })),
);
const AccommodationDetailPage = lazy(() =>
  import('@/features/accommodation').then((m) => ({
    default: m.AccommodationDetailPage,
  })),
);
const AccommodationCalendarPage = lazy(() =>
  import('@/features/accommodation').then((m) => ({
    default: m.AccommodationCalendar,
  })),
);
const PropertyDevHouseTypeSettingsPage = lazy(() =>
  import('@/features/property-dev').then((m) => ({
    default: m.HouseTypeSettingsPage,
  }))
);
// (ValidationRulesSettingsPage now mounts inside GovernancePage — see below.)
const PropertyDevDocumentTemplatesSettingsPage = lazy(() =>
  import('@/features/property-dev').then((m) => ({
    default: m.DocumentTemplatesSettingsPage,
  })),
);
const PropertyDevPricingEnginePage = lazy(() =>
  import('@/features/property-dev').then((m) => ({
    default: m.PricingEnginePage,
  })),
);
const PropertyDevBulkOperationsPage = lazy(() =>
  import('@/features/property-dev').then((m) => ({
    default: m.BulkOperationsPage,
  })),
);
// ── Geo Hub — Cesium 3D Tiles + cross-module geo. Lazy-loaded because
// CesiumJS is ~3 MB; this keeps the main bundle untouched.
const GeoHubAdminPage = lazy(() =>
  import('@/features/geo-hub/GeoHubAdminPage').then((m) => ({ default: m.GeoHubAdminPage }))
);
const GeoHubPage = lazy(() =>
  import('@/features/geo-hub').then((m) => ({ default: m.GeoHubPage }))
);
const ProjectGeoPage = lazy(() =>
  import('@/features/geo-hub').then((m) => ({ default: m.ProjectGeoPage }))
);
const DevelopmentGeoPage = lazy(() =>
  import('@/features/geo-hub').then((m) => ({ default: m.DevelopmentGeoPage }))
);
const PropertyDevDashboardsHub = lazy(() =>
  import('@/features/property-dev/dashboards').then((m) => ({
    default: m.DashboardsHub,
  })),
);
const PropertyDevDashboardFullView = lazy(() =>
  import('@/features/property-dev/dashboards').then((m) => ({
    default: m.FullViewPage,
  })),
);
const BidManagementPage = lazy(() =>
  import('@/features/bid-management').then((m) => ({ default: m.BidManagementPage }))
);
const VariationsPage = lazy(() =>
  import('@/features/variations').then((m) => ({ default: m.VariationsPage }))
);
const ScheduleAdvancedPage = lazy(() =>
  import('@/features/schedule-advanced').then((m) => ({ default: m.ScheduleAdvancedPage }))
);
const TaktSchedulePage = lazy(() =>
  import('@/features/schedule-advanced').then((m) => ({ default: m.TaktSchedulePage }))
);
const HSEAdvancedPage = lazy(() =>
  import('@/features/hse-advanced').then((m) => ({ default: m.HSEAdvancedPage }))
);
const DailyDiaryPage = lazy(() =>
  import('@/features/daily-diary').then((m) => ({ default: m.DailyDiaryPage }))
);
const QMSPage = lazy(() =>
  import('@/features/qms').then((m) => ({ default: m.QMSPage }))
);
const SupplierCatalogsPage = lazy(() =>
  import('@/features/supplier-catalogs').then((m) => ({ default: m.SupplierCatalogsPage }))
);
const BIDashboardsPage = lazy(() =>
  import('@/features/bi-dashboards').then((m) => ({ default: m.BIDashboardsPage }))
);
const ProjectControlsPage = lazy(() =>
  import('@/features/project-controls').then((m) => ({ default: m.ProjectControlsPage }))
);
// v4.1 — three additional P1 Slice-1 features land behind dedicated routes
// (Assembly Library was already eagerly imported by the assemblies feature
// index in its Slice-1 PR). Pages are net-new so they pile on the end of
// the lazy-import block to keep diffs surgical.
const FederationsPage = lazy(() =>
  import('@/features/bim/FederationsPage').then((m) => ({ default: m.FederationsPage }))
);
const CoordinationHubPage = lazy(() =>
  import('@/features/coordination/CoordinationHubPage').then((m) => ({
    default: m.CoordinationHubPage,
  }))
);
const CPMView = lazy(() =>
  import('@/features/schedule/CPMView').then((m) => ({ default: m.CPMView }))
);
const AgentsPage = lazy(() =>
  import('@/features/ai-agents').then((m) => ({ default: m.AgentsPage }))
);

// Admin/settings/assemblies — code-split out of the boot bundle.
// These pages are reachable from the sidebar but not part of the default
// landing flow, so keeping them lazy trims the initial chunk significantly
// (v4.3 audit). Deep-imported by file path to avoid pulling neighbouring
// pages via barrel re-exports.
const SettingsPage = lazy(() =>
  import('@/features/settings/SettingsPage').then((m) => ({ default: m.SettingsPage }))
);
const ModulesPage = lazy(() =>
  import('@/features/modules/ModulesPage').then((m) => ({ default: m.ModulesPage }))
);
const ModuleDeveloperGuide = lazy(() =>
  import('@/features/modules/ModuleDeveloperGuide').then((m) => ({ default: m.ModuleDeveloperGuide }))
);
const AssembliesPage = lazy(() =>
  import('@/features/assemblies/AssembliesPage').then((m) => ({ default: m.AssembliesPage }))
);
const AssemblyEditorPage = lazy(() =>
  import('@/features/assemblies/AssemblyEditorPage').then((m) => ({ default: m.AssemblyEditorPage }))
);
const AssemblyLibraryPage = lazy(() =>
  import('@/features/assemblies/AssemblyLibraryPage').then((m) => ({ default: m.AssemblyLibraryPage }))
);
const CreateAssemblyPage = lazy(() =>
  import('@/features/assemblies/CreateAssemblyPage').then((m) => ({ default: m.CreateAssemblyPage }))
);
const ImportDatabasePage = lazy(() =>
  import('@/features/costs/ImportDatabasePage').then((m) => ({ default: m.ImportDatabasePage }))
);
const OnboardingWizard = lazy(() =>
  import('@/features/onboarding/OnboardingWizard').then((m) => ({ default: m.OnboardingWizard }))
);
const LoginPageNext = lazy(() =>
  import('@/features/auth/LoginPageNext').then((m) => ({ default: m.LoginPageNext }))
);
const QuickEstimatePage = lazy(() =>
  import('@/features/ai/QuickEstimatePage').then((m) => ({ default: m.QuickEstimatePage }))
);
const AiEstimatorPage = lazy(() =>
  import('@/features/ai-estimator/AiEstimatorPage').then((m) => ({ default: m.AiEstimatorPage }))
);

// Rarely-visited or heavy secondary pages — moved out of the initial
// `index` bundle (was eager via barrel imports, ~1.4 MB chunk; these
// surfaces are not part of the post-login landing flow).
const CostsPage = lazy(() =>
  import('@/features/costs').then((m) => ({ default: m.CostsPage }))
);
const ValidationPage = lazy(() =>
  import('@/features/validation').then((m) => ({ default: m.ValidationPage }))
);
const QuantitiesPage = lazy(() =>
  import('@/features/quantities').then((m) => ({ default: m.QuantitiesPage }))
);
const IntegrationsPage = lazy(() =>
  import('@/features/integrations').then((m) => ({ default: m.IntegrationsPage }))
);
const AboutPage = lazy(() =>
  import('@/features/about/AboutPage').then((m) => ({ default: m.AboutPage }))
);

// CPMView is keyed by the schedule it analyses, so the route reads :id and
// forwards it through. Kept as a tiny inline component to avoid bloating
// the schedule feature with a route-wrapper that only exists for App.tsx.
function CPMViewRoute() {
  const { id } = useParams<{ id: string }>();
  if (!id) return null;
  return <CPMView scheduleId={id} />;
}

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

// Small inline loader for lazy page chunks — shown inside the main content
// area while the layout (sidebar + header) stays visible. Prevents the
// full-screen dark flash when navigating between code-split routes (e.g.
// clicking a notification that links to /tasks or /cde).
function PageLoadingInline() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
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

// Lets each page hand its header title up to the persistent AppShell.
const PageTitleContext = createContext<(title: string) => void>(() => {});

// The persistent application shell.  Previously every protected route's element
// was `<P title><Page/></P>`, and because <AppLayout> (the sidebar + header)
// lived INSIDE each route element, React Router tore the whole chrome down and
// rebuilt it on every navigation — the same per-route remount that forced
// ProductTour out of AppLayout (see AppLayout's BUG-UI02 note) and that made
// each module feel slow to open.  AppShell hoists AppLayout above the router
// <Outlet/> so the sidebar + header mount exactly once and only the page area
// swaps.  The ErrorBoundary is keyed by pathname so a crashed page recovers on
// the next navigation, matching the old per-route boundary; the Suspense
// boundary stays mounted so the v7 startTransition smooth-nav keeps the
// previous page on screen while the next chunk loads.
function AppShell() {
  const [title, setTitle] = useState('');
  const location = useLocation();
  return (
    <RequireAuth>
      <AppLayout title={title}>
        <Suspense fallback={<PageLoadingInline />}>
          <ErrorBoundary key={location.pathname}>
            <PageTitleContext.Provider value={setTitle}>
              <Outlet />
            </PageTitleContext.Provider>
          </ErrorBoundary>
        </Suspense>
      </AppLayout>
    </RequireAuth>
  );
}

// Per-page wrapper kept at every route call site.  It no longer builds its own
// layout — it just publishes the page's header title to the surrounding
// AppShell.  useLayoutEffect runs before paint so the heading swaps without a
// visible flash of the previous page's title.
function P({ title, children }: { title: string; children: React.ReactNode }) {
  const setTitle = useContext(PageTitleContext);
  useLayoutEffect(() => {
    setTitle(title);
  }, [setTitle, title]);
  return <>{children}</>;
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
  const closeGlobalSearch = useGlobalSearchStore((s) => s.closeModal);

  // The command palette (Ctrl+K, local state) and the global semantic search
  // modal (Ctrl+Shift+K, zustand) are two separate launcher surfaces that both
  // render at z-[60]. The palette uses createPortal to document.body and sits
  // later in the DOM, so when both are open it paints on top of the search
  // modal. Keep them mutually exclusive: opening one closes the other in both
  // directions.
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
        // If the search is currently closed it is about to open, so close the
        // command palette to keep the two launchers mutually exclusive. Read
        // the live store state since toggleModal() does not return the result.
        if (!useGlobalSearchStore.getState().open) {
          setPaletteOpen(false);
        }
        toggleGlobalSearch();
        return;
      }

      if (isTextField) return;

      if (mod && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen((prev) => {
          const next = !prev;
          // Opening the palette closes the global search modal.
          if (next) closeGlobalSearch();
          return next;
        });
      }
      if (e.key === '/' && !mod) {
        e.preventDefault();
        // Opening the palette closes the global search modal.
        closeGlobalSearch();
        setPaletteOpen(true);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [toggleGlobalSearch, openGlobalSearch, closeGlobalSearch]);

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

// Refresh the authoritative role from the server so a user whose role was
// changed by an admin sees the correct UI immediately on the next page load,
// without waiting for their token to expire (RBAC stale-role fix).
// Fire-and-forget — a network failure here is non-fatal; the JWT-decoded role
// remains available as a fallback.
useAuthStore.getState().syncRoleFromServer();

// Initialize the anonymized error logger (global handlers for unhandled errors)
initErrorLogger();

// Inject DDC origin meta tags + subtle console banner. These provide
// provenance fingerprints: if someone clones the UI and serves it
// unmodified, the meta tags and console message are direct evidence of
// the origin. Removing them is not a functional break, but does prove
// the distribution was tampered with.
if (typeof document !== 'undefined') {
  ddcInjectMeta();
}
if (typeof window !== 'undefined' && typeof console !== 'undefined') {
  try {
    // eslint-disable-next-line no-console
    console.info(
      `%c${DDC_ORIGIN}%c · Artem Boiko · datadrivenconstruction.io`,
      'color:#0071E3;font-weight:700',
      'color:#64748b',
    );
  } catch { /* noop */ }
}

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

  // Pull the user's saved custom-unit catalogue once after auth resolves.
  // Fire-and-forget — the BOQ Unit dropdown still works from localStorage
  // before this completes; the server merge just keeps it consistent across
  // browsers and sessions.
  useEffect(() => {
    if (!isAuthenticated) return;
    void syncCustomUnitsFromServer();
  }, [isAuthenticated]);

  // Onboarding-tour migration (one-shot). The app used to mount two
  // parallel tour systems — `OnboardingTour` (storage key
  // `oe_tour_completed`, underscore) and `ProductTour` (storage key
  // `oe.tour_completed`, dot). A user dismissing one would still see
  // the other pop on the next page. We've collapsed onto ProductTour
  // alone; this effect ports the legacy dismissed-flag forward so a
  // returning user who already saw the old tour doesn't see the new
  // one again. The legacy key is then deleted so the migration runs
  // exactly once per browser.
  useEffect(() => {
    try {
      const legacy = localStorage.getItem('oe_tour_completed');
      if (legacy !== null) {
        const current = localStorage.getItem('oe.tour_completed');
        if (current === null) {
          localStorage.setItem('oe.tour_completed', legacy);
        }
        localStorage.removeItem('oe_tour_completed');
      }
    } catch {
      /* localStorage unavailable — non-fatal, ProductTour falls back
         to server-side tour-state on next mount. */
    }
  }, []);

  // Dynamic routes from the module registry (lazy-loaded)
  const moduleRoutes = useModuleRouteElements({ Wrapper: P });

  return (
    <Suspense fallback={<LoadingScreen />}>
      {/* Route-transition pending feedback: under v7_startTransition the
          old page stays on screen while a lazy chunk loads, so this binder
          drives the top progress bar + sidebar row spinner for the gap
          between history push and location commit (navigationProgress.ts). */}
      <NavigationProgress />
      <OfflineBanner />
      {isAuthenticated && <GlobalShortcuts />}
      {/* First-run product tour — 8-step spotlight walk-through. Always
          mounted (for authenticated users) but renders nothing unless
          active; auto-starts on the dashboard the first time a user
          logs in (gated by `oe.tour_completed` in localStorage) and
          listens for the `oe:start-tour` window event so the
          WhatsNewCard / Help menu can (re-)launch it on demand.

          UX-audit collapse: the older `OnboardingTour` (storage key
          `oe_tour_completed`, no dot) used to be mounted here in
          parallel — dismissing one still let the other pop on the
          next page. ProductTour now owns the global tour surface;
          a one-shot legacy-key migration in the effect above
          forwards a dismissed flag from the old storage key so
          returning users don't see the tour again. The
          `OnboardingTour` component still ships for per-feature
          custom tours (e.g. Pipelines page), but is no longer mounted
          globally. */}
      {isAuthenticated && <ProductTour />}
      <Routes>
        {/* Public share-link landing page — no auth required, no app shell */}
        <Route path="/share/:token" element={<SharePage />} />

        {/* Public buyer-portal landing page — magic-link auth only, no app shell */}
        <Route path="/buyer-portal/:token" element={<BuyerPortalPage />} />

        {/* Public subcontractor payment portal — magic-link session, no app
            shell. ?token=<magic-link> deep-links straight to the submit form
            after auth; a return visit reuses the stored session token. */}
        <Route path="/portal/payments" element={<PortalPaymentsPage />} />

        {/* Field-worker mobile shell — bottom-nav layout, no desktop sidebar.
            `/field/{token}` is the SMS magic-link PIN-redemption screen; it
            consumes the link and routes to `/field`, the four-tab shell.
            Both are session-driven (no JWT) and degrade gracefully to a
            signed-out hint when no field session is present.
            See docs/architecture/FIELD_WORKER_MOBILE_DESIGN.md */}
        <Route
          path="/field/:token"
          element={
            <Suspense fallback={<LoadingScreen />}>
              <FieldAuthPage />
            </Suspense>
          }
        />
        <Route
          path="/field"
          element={
            <Suspense fallback={<LoadingScreen />}>
              <FieldShellPage />
            </Suspense>
          }
        />

        {/* Auth — public */}
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/login-next" element={isAuthenticated ? <Navigate to="/" replace /> : <Suspense fallback={<LoadingScreen />}><LoginPageNext /></Suspense>} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" replace /> : <RegisterPage />} />
        <Route path="/forgot-password" element={isAuthenticated ? <Navigate to="/" replace /> : <ForgotPasswordPage />} />

        {/* Onboarding — full-screen, no layout */}
        <Route path="/onboarding" element={
          <RequireAuth><Suspense fallback={<LoadingScreen />}><OnboardingWizard /></Suspense></RequireAuth>
        } />

        {/* App — all protected, all real pages.  Every route below shares one
            persistent <AppShell/> (sidebar + header mount once); the matched
            page renders into its <Outlet/>.  RequireAuth lives in AppShell, so
            the inner per-page `<P>` only sets the header title now. */}
        <Route element={<AppShell />}>
        {/* BUG-215 — authenticated users hitting `/` land on the dashboard
            (the canonical post-login surface). Unauthenticated users fall
            through to RequireAuth in AppShell and are bounced to /login
            (preserving the marketing-flavoured public landing path). */}
        <Route
          path="/"
          element={
            isAuthenticated
              ? <Navigate to="/dashboard" replace />
              : <P title="Dashboard"><DashboardPage /></P>
          }
        />

        <Route path="/ai-estimate" element={<P title="AI Quick Estimate"><QuickEstimatePage /></P>} />
        <Route path="/ai-estimator" element={<P title="AI Estimate Builder"><AiEstimatorPage /></P>} />
        <Route path="/ai-agents" element={<P title="AI Agents"><AgentsPage /></P>} />
        <Route path="/advisor" element={<P title="AI Cost Advisor"><AdvisorPage /></P>} />
        <Route path="/chat" element={<P title="AI Chat"><ERPChatPage /></P>} />
        <Route path="/chat/admin" element={<P title="Chat Observability"><ERPChatAdminStatsPage /></P>} />
        <Route path="/cad-takeoff" element={<Navigate to="/data-explorer" replace />} />
        <Route path="/cad-explorer" element={<Navigate to="/data-explorer" replace />} />
        <Route path="/data-explorer" element={<P title="Data Explorer"><CadDataExplorerPage /></P>} />
        <Route path="/match-elements" element={<P title="Match Elements"><MatchElementsPage /></P>} />
        <Route path="/pointcloud" element={<P title="Point Cloud"><PointCloudPage /></P>} />
        <Route path="/bim" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/bim/federations" element={<P title="BIM Federations"><FederationsPage /></P>} />
        <Route path="/bim/rules" element={<P title="BIM Rules"><BIMQuantityRulesPage /></P>} />
        {/* Legacy alias — must come BEFORE /bim/:modelId so the literal
            "quantity-rules" segment isn't swallowed as a UUID model id. */}
        <Route path="/bim/quantity-rules" element={<Navigate to="/bim/rules" replace />} />
        <Route path="/clash" element={<P title="Clash Detection"><ClashDetectionPage /></P>} />
        <Route path="/clash/profiles" element={<P title="Clash Profiles"><ClashProfileManager /></P>} />
        <Route path="/projects/:projectId/clash/profiles" element={<P title="Clash Profiles"><ClashProfileManager /></P>} />
        <Route path="/coordination" element={<P title="Model Coordination"><CoordinationHubPage /></P>} />
        <Route path="/assets" element={<P title="Asset Register"><AssetsPage /></P>} />
        <Route path="/bim/:modelId" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/projects/:projectId/bim" element={<P title="BIM Viewer"><BIMPage /></P>} />
        <Route path="/projects/:projectId/bim/:modelId" element={<P title="BIM Viewer"><BIMPage /></P>} />

        <Route path="/projects" element={<P title="Projects"><ProjectsPage /></P>} />
        <Route path="/projects/new" element={<P title="New Project"><CreateProjectPage /></P>} />
        <Route path="/projects/:projectId" element={<P title="Project"><ProjectDetailPage /></P>} />
        <Route path="/projects/:projectId/settings" element={<P title="Project Settings"><ProjectSettingsPage /></P>} />
        <Route path="/projects/:projectId/boq/new" element={<P title="New BOQ"><CreateBOQPage /></P>} />
        <Route path="/projects/:projectId/boq" element={<P title="Bill of Quantities"><BOQListPage /></P>} />

        <Route path="/boq" element={<P title="Bill of Quantities"><BOQListPage /></P>} />
        <Route path="/boq/:boqId" element={<P title="BOQ Editor"><BOQEditorPage /></P>} />
        <Route path="/templates" element={<P title="BOQ Templates"><TemplatesPage /></P>} />

        <Route path="/costs" element={<P title="Cost Database"><CostsPage /></P>} />
        <Route path="/costs/import" element={<P title="Import Cost Database"><ImportDatabasePage /></P>} />

        <Route path="/catalog" element={<P title="Resource Catalog"><CatalogPage /></P>} />

        <Route path="/assemblies" element={<P title="Assemblies"><AssembliesPage /></P>} />
        <Route path="/assemblies/library" element={<P title="Assembly Library"><AssemblyLibraryPage /></P>} />
        <Route path="/assemblies/new" element={<P title="New Assembly"><CreateAssemblyPage /></P>} />
        <Route path="/assemblies/:assemblyId" element={<P title="Assembly Editor"><AssemblyEditorPage /></P>} />

        <Route path="/validation" element={<P title="Validation"><ValidationPage /></P>} />
        <Route path="/compliance/builder" element={<P title="Compliance Rule Builder"><NlRuleBuilderPanel /></P>} />

        <Route path="/quantities" element={<P title="Quantity Takeoff"><QuantitiesPage /></P>} />
        <Route path="/takeoff" element={<P title="PDF Takeoff"><TakeoffPage /></P>} />
        <Route path="/dwg-takeoff" element={<P title="DWG Takeoff"><DwgTakeoffPage /></P>} />

        <Route path="/schedule" element={<P title="4D Schedule"><SchedulePage /></P>} />
        <Route path="/schedule/:id/cpm" element={<P title="CPM"><CPMViewRoute /></P>} />

        <Route path="/5d" element={<P title="5D Cost Model"><CostModelPage /></P>} />

        <Route path="/analytics" element={<P title="Analytics"><AnalyticsPage /></P>} />

        <Route path="/dashboards" element={<P title="Dashboards"><SnapshotsPage /></P>} />
        <Route path="/projects/:projectId/dashboards" element={<P title="Dashboards"><SnapshotsPage /></P>} />

        <Route path="/reports" element={<P title="Reports"><ReportsPage /></P>} />
        <Route path="/reporting" element={<P title="Reporting Dashboards"><ReportingPage /></P>} />

        <Route path="/tendering" element={<P title="Tendering"><TenderingPage /></P>} />

        <Route path="/changeorders" element={<P title="Change Orders"><ChangeOrdersPage /></P>} />
        <Route path="/documents" element={<Navigate to="/files" replace />} />
        <Route path="/photos" element={<P title="Project Photos"><PhotoGalleryPage /></P>} />
        <Route path="/files/trash" element={<P title="Recycle Bin"><TrashPage /></P>} />
        <Route path="/files/search" element={<P title="Search across projects"><GlobalSearchPage /></P>} />
        <Route path="/files/transmittals" element={<P title="Transmittals"><TransmittalLogPage /></P>} />
        <Route path="/files" element={<P title="Project Files"><FileManagerPage /></P>} />
        <Route path="/projects/:projectId/files" element={<P title="Project Files"><FileManagerPage /></P>} />

        <Route path="/risks" element={<P title="Risk Register"><RiskRegisterPage /></P>} />

        {/* Requirements merged into BIM Rules page */}
        <Route path="/requirements" element={<Navigate to="/bim/rules" replace />} />
        <Route
          path="/requirements/matrix"
          element={<P title="EIR Matrix"><RequirementsMatrixPage /></P>}
        />

        <Route path="/markups" element={<P title="Markups"><MarkupsPage /></P>} />
        <Route path="/markups/compare" element={<P title="Compare Revisions"><PdfComparePage /></P>} />
        <Route path="/punchlist" element={<P title="Punch List"><PunchListPage /></P>} />
        <Route path="/closeout" element={<P title="Handover & Closeout"><CloseoutPage /></P>} />
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
        <Route path="/rfi/:rfiId" element={<P title="RFI"><RFIDetailPage /></P>} />
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
        <Route path="/projects/:projectId/moc" element={<P title="Management of Change"><MoCPage /></P>} />
        <Route path="/moc" element={<P title="Management of Change"><MoCPage /></P>} />

        <Route path="/users" element={<P title="User Management"><UserManagementPage /></P>} />
        <Route path="/admin/audit-log" element={<P title="Audit Log"><AuditLogPage /></P>} />
        {/* Governance — merged home for Permissions, Approval Routes and
            Validation Rules (three /modules-style top tabs). The active
            tab is driven by ?tab=permissions|approvals|validation. */}
        <Route path="/governance" element={<P title="Governance"><GovernancePage /></P>} />
        {/* The three standalone pages now live as Governance tabs (mounted
            inside GovernancePage). Redirect old links — and any internal
            navigations — to the matching tab so nothing breaks. */}
        <Route path="/admin/permissions" element={<Navigate to="/governance?tab=permissions" replace />} />
        <Route path="/admin/webhook-targets" element={<P title="Webhook Targets"><WebhookTargetsPage /></P>} />
        <Route path="/admin/validation-rules" element={<Navigate to="/governance?tab=validation" replace />} />
        <Route path="/approval-routes" element={<Navigate to="/governance?tab=approvals" replace />} />
        {/* Legacy redirect — moved 2026-05-23 from PropDev settings; now to Governance. */}
        <Route path="/property-dev/settings/validation-rules" element={<Navigate to="/governance?tab=validation" replace />} />
        <Route path="/modules" element={<P title="Modules"><ModulesPage /></P>} />
        <Route path="/modules/developer-guide" element={<P title="Module Developer Guide"><ModuleDeveloperGuide /></P>} />

        <Route path="/setup/databases" element={<P title="Databases & Resources"><DatabaseSetupPage /></P>} />
        <Route path="/settings" element={<P title="Settings"><SettingsPage /></P>} />
        <Route path="/integrations" element={<P title="Integrations"><IntegrationsPage /></P>} />
        <Route path="/about" element={<P title="About"><AboutPage /></P>} />
        <Route path="/project-intelligence" element={<P title="Project Intelligence"><ProjectIntelligencePage /></P>} />
        {/* Architecture Map — internal tool, admin-only. Surfaces module
            dependency graph + DDC integrity audit; not for day-to-day use. */}
        <Route
          path="/architecture"
          element={
            <AdminOnly>
              <P title="Architecture Map"><ArchitectureMapPage /></P>
            </AdminOnly>
          }
        />

        {/* EAC v2 (RFC 35) — block editor primitives preview, dev-only.
            Both the demo page and the orphan block-editor route are
            gated to admins so a regular customer can't stumble into the
            unfinished editor by URL. */}
        <Route
          path="/eac/demo"
          element={
            <AdminOnly>
              <P title="EAC Block Primitives"><EacDemoPage /></P>
            </AdminOnly>
          }
        />
        <Route
          path="/eac/blocks/:eacId"
          element={
            <AdminOnly>
              <P title="EAC Block Editor"><EACBlockEditorPage /></P>
            </AdminOnly>
          }
        />

        {/* Styles Lab — design exploration, internal; admin-only so the
            design system playground doesn't bleed into the customer UX. */}
        <Route
          path="/styles-lab"
          element={
            <AdminOnly>
              <P title="Styles Lab"><StylesLabPage /></P>
            </AdminOnly>
          }
        />

        {/* 18-Modules Wave — Field Operations */}
        <Route path="/service" element={<P title="Service & Maintenance"><ServicePage /></P>} />
        <Route path="/projects/:projectId/service" element={<P title="Service & Maintenance"><ServicePage /></P>} />
        <Route path="/equipment" element={<P title="Equipment & Fleet"><EquipmentPage /></P>} />
        <Route path="/projects/:projectId/equipment" element={<P title="Equipment & Fleet"><EquipmentPage /></P>} />
        <Route path="/payroll" element={<P title="Payroll"><PayrollPage /></P>} />
        <Route path="/projects/:projectId/payroll" element={<P title="Payroll"><PayrollPage /></P>} />
        <Route path="/daily-diary" element={<P title="Daily Diary"><DailyDiaryPage /></P>} />
        <Route path="/projects/:projectId/daily-diary" element={<P title="Daily Diary"><DailyDiaryPage /></P>} />
        <Route path="/portal" element={<P title="Client & Partner Portal"><PortalPage /></P>} />
        <Route path="/projects/:projectId/portal" element={<P title="Client & Partner Portal"><PortalPage /></P>} />
        <Route path="/resources" element={<P title="Resources & Crew"><ResourcesPage /></P>} />
        <Route path="/projects/:projectId/resources" element={<P title="Resources & Crew"><ResourcesPage /></P>} />
        <Route path="/portfolio/capacity" element={<P title="Capacity Planning"><CapacityPlanningPage /></P>} />
        <Route path="/portfolio/leveling" element={<P title="Resource Leveling"><ResourceLevelingPage /></P>} />

        {/* 18-Modules Wave — Commercial */}
        <Route path="/contracts" element={<P title="Contracts"><ContractsPage /></P>} />
        <Route path="/projects/:projectId/contracts" element={<P title="Contracts"><ContractsPage /></P>} />
        <Route path="/projects/:projectId/contracts/claims/:claimId" element={<P title="Progress Claim"><ProgressClaimDetailPage /></P>} />
        <Route path="/subcontractors" element={<P title="Subcontractors"><SubcontractorsPage /></P>} />
        <Route path="/projects/:projectId/subcontractors" element={<P title="Subcontractors"><SubcontractorsPage /></P>} />
        <Route path="/bid-management" element={<P title="Bid Management"><BidManagementPage /></P>} />
        <Route path="/projects/:projectId/bid-management" element={<P title="Bid Management"><BidManagementPage /></P>} />
        <Route path="/crm" element={<P title="CRM"><CRMPage /></P>} />
        <Route path="/property-dev" element={<P title="Property Development"><PropertyDevPage /></P>} />
        <Route path="/property-dev/developments/:devId/geo" element={<P title="Development map"><DevelopmentGeoPage /></P>} />
        <Route path="/property-dev/developments/:devId/pricing" element={<P title="Pricing Engine"><PropertyDevPricingEnginePage /></P>} />
        <Route path="/property-dev/developments/:devId/inventory-map" element={<P title="Inventory Map"><PropertyDevInventoryMapPage /></P>} />
        <Route path="/property-dev/admin/bulk-operations" element={<P title="Bulk Operations"><PropertyDevBulkOperationsPage /></P>} />
        <Route path="/property-dev/dashboards" element={<P title="Property Development Dashboards"><PropertyDevDashboardsHub /></P>} />
        <Route
          path="/property-dev/settings/house-types"
          element={
            <P title="House Type Catalogue"><PropertyDevHouseTypeSettingsPage /></P>
          }
        />
        <Route
          path="/property-dev/settings/document-templates"
          element={
            <P title="Document Templates"><PropertyDevDocumentTemplatesSettingsPage /></P>
          }
        />
        <Route
          path="/property-dev/admin/bulk-operations"
          element={
            <P title="Bulk Operations"><PropertyDevBulkOperationsPage /></P>
          }
        />
        <Route path="/property-dev/dashboards/:key" element={<P title="Property Development Dashboard"><PropertyDevDashboardFullView /></P>} />
        <Route path="/accommodation" element={<P title="Accommodation"><AccommodationListPage /></P>} />
        <Route path="/accommodation/calendar" element={<P title="Accommodation Calendar"><AccommodationCalendarPage /></P>} />
        <Route path="/accommodation/:id" element={<P title="Accommodation"><AccommodationDetailPage /></P>} />
        <Route path="/supplier-catalogs" element={<P title="Supplier Catalogs"><SupplierCatalogsPage /></P>} />

        {/* Geo Hub — Cesium 3D Tiles + cross-module geo. */}
        <Route path="/geo" element={<P title="Geo Hub"><GeoHubPage /></P>} />
        <Route path="/geo/admin" element={<P title="Geo Hub Admin"><GeoHubAdminPage /></P>} />
        <Route path="/geo-hub" element={<Navigate to="/geo" replace />} />
        <Route path="/geo-hub/admin" element={<Navigate to="/geo/admin" replace />} />
        <Route path="/projects/:projectId/geo" element={<P title="Project map"><ProjectGeoPage /></P>} />
        <Route path="/projects/:projectId/geo-hub" element={<Navigate to="/geo" replace />} />

        {/* 18-Modules Wave — Schedule & Quality */}
        <Route path="/schedule-advanced" element={<P title="Advanced Schedule"><ScheduleAdvancedPage /></P>} />
        <Route path="/projects/:projectId/schedule-advanced" element={<P title="Advanced Schedule"><ScheduleAdvancedPage /></P>} />
        <Route path="/takt" element={<P title="Takt Planning"><TaktSchedulePage /></P>} />
        <Route path="/projects/:projectId/takt" element={<P title="Takt Planning"><TaktSchedulePage /></P>} />
        <Route path="/qms" element={<P title="Quality Management"><QMSPage /></P>} />
        <Route path="/projects/:projectId/qms" element={<P title="Quality Management"><QMSPage /></P>} />
        <Route path="/hse-advanced" element={<P title="HSE Management"><HSEAdvancedPage /></P>} />
        <Route path="/projects/:projectId/hse-advanced" element={<P title="HSE Management"><HSEAdvancedPage /></P>} />
        <Route path="/carbon" element={<P title="Carbon & ESG"><CarbonPage /></P>} />
        <Route path="/projects/:projectId/carbon" element={<P title="Carbon & ESG"><CarbonPage /></P>} />
        <Route path="/bi-dashboards" element={<P title="BI Dashboards"><BIDashboardsPage /></P>} />
        <Route path="/projects/:projectId/bi-dashboards" element={<P title="BI Dashboards"><BIDashboardsPage /></P>} />
        <Route path="/project-controls" element={<P title="Project Controls"><ProjectControlsPage /></P>} />
        <Route path="/projects/:projectId/project-controls" element={<P title="Project Controls"><ProjectControlsPage /></P>} />

        {/* Convenience route aliases — redirect to canonical paths */}
        {/* `/dashboard` renders DashboardPage directly. The earlier alias
            redirected to `/`, but BUG-215 made `/` redirect authed users to
            `/projects`, leaving DashboardPage unreachable. */}
        <Route path="/dashboard" element={<P title="Dashboard"><DashboardPage /></P>} />
        <Route path="/change-orders" element={<Navigate to="/changeorders" replace />} />
        <Route path="/punch-list" element={<Navigate to="/punchlist" replace />} />
        {/* Variations (FIDIC/JCT VOs) — distinct from generic change-orders;
            its own register tracks contractual variation instructions with
            day-works, instructions, time-impact analysis. */}
        <Route path="/variations" element={<P title="Variations"><VariationsPage /></P>} />
        <Route path="/projects/:projectId/variations" element={<P title="Variations"><VariationsPage /></P>} />
        <Route path="/estimates" element={<Navigate to="/boq" replace />} />
        <Route path="/profile" element={<Navigate to="/settings" replace />} />
        <Route path="/notifications" element={<P title="Notifications"><NotificationsPage /></P>} />

        {/* Plugin module routes — lazy-loaded */}
        {moduleRoutes}

        {/* 404 — catch-all for unknown routes */}
        <Route path="*" element={isAuthenticated ? <P title="Not Found"><NotFoundPage /></P> : <Navigate to="/login" replace />} />
        </Route>
      </Routes>
      <ToastContainer />
      {/* Non-blocking progress for a ready-made pack that keeps provisioning
          (cost databases, modules, sample projects) in the background after the
          user has already entered the app from onboarding. Mounted at the root
          so it survives navigation; no-op until an install is in flight. */}
      <BackgroundInstallBanner />
      <FloatingQueuePanel />
      {/* Mobile PWA — Slice 1.  Single, discrete install nudge handled
          entirely inside <PWAInstallPrompt /> (cooldown, iOS branch,
          standalone-mode detection).  Safe to mount unauthenticated:
          on login screen the user may also want to install the app. */}
      <PWAInstallPrompt />
      {/* DDC-CWICR-OE */}
      <span aria-hidden="true" style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}>
        {'\u200B\u200C\u200D\u200B\u200C\u200D\u200B'}
        DataDrivenConstruction·CWICR·OpenConstructionERP·2026
      </span>
    </Suspense>
  );
}
