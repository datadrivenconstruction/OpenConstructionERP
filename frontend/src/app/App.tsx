import { Suspense, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage } from '@/features/auth';
import { ProjectsPage, CreateProjectPage, ProjectDetailPage } from '@/features/projects';
import { BOQEditorPage, CreateBOQPage } from '@/features/boq';
import { CostsPage } from '@/features/costs';
import { ValidationPage } from '@/features/validation';
import { useAuthStore } from '@/stores/useAuthStore';

function LoadingScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-secondary">
      <div className="flex flex-col items-center gap-3 animate-fade-in">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue shadow-md">
          <span className="text-lg font-bold text-white">OE</span>
        </div>
        <div className="h-1 w-16 overflow-hidden rounded-full bg-surface-secondary">
          <div className="h-full w-8 animate-shimmer rounded-full bg-oe-blue opacity-60" />
        </div>
      </div>
    </div>
  );
}

function PlaceholderPage({ titleKey }: { titleKey: string }) {
  const { t } = useTranslation();
  return (
    <AppLayout title={t(titleKey)}>
      <div className="flex flex-col items-center justify-center py-24 text-center animate-fade-in">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-secondary">
          <span className="text-xl text-content-tertiary">Soon</span>
        </div>
        <h2 className="text-xl font-semibold text-content-primary">{t(titleKey)}</h2>
        <p className="mt-2 text-sm text-content-secondary">Coming soon</p>
      </div>
    </AppLayout>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return (
    <Suspense fallback={<LoadingScreen />}>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />

        {/* Dashboard */}
        <Route
          path="/"
          element={
            <RequireAuth>
              <AppLayout title="Dashboard">
                <DashboardPage />
              </AppLayout>
            </RequireAuth>
          }
        />

        {/* Protected routes */}
        <Route path="/projects" element={<RequireAuth><AppLayout title="Projects"><ProjectsPage /></AppLayout></RequireAuth>} />
        <Route path="/projects/new" element={<RequireAuth><AppLayout title="New Project"><CreateProjectPage /></AppLayout></RequireAuth>} />
        <Route path="/projects/:projectId" element={<RequireAuth><AppLayout title="Project"><ProjectDetailPage /></AppLayout></RequireAuth>} />
        <Route path="/projects/:projectId/boq/new" element={<RequireAuth><AppLayout title="New BOQ"><CreateBOQPage /></AppLayout></RequireAuth>} />
        <Route path="/boq/:boqId" element={<RequireAuth><AppLayout title="BOQ Editor"><BOQEditorPage /></AppLayout></RequireAuth>} />
        <Route path="/costs" element={<RequireAuth><AppLayout title="Cost Database"><CostsPage /></AppLayout></RequireAuth>} />
        <Route path="/validation" element={<RequireAuth><AppLayout title="Validation"><ValidationPage /></AppLayout></RequireAuth>} />
        <Route path="/boq" element={<RequireAuth><PlaceholderPage titleKey="boq.title" /></RequireAuth>} />
        <Route path="/takeoff" element={<RequireAuth><PlaceholderPage titleKey="takeoff.title" /></RequireAuth>} />
        <Route path="/tendering" element={<RequireAuth><PlaceholderPage titleKey="tendering.title" /></RequireAuth>} />
        <Route path="/modules" element={<RequireAuth><PlaceholderPage titleKey="modules.title" /></RequireAuth>} />
        <Route path="/settings" element={<RequireAuth><PlaceholderPage titleKey="nav.settings" /></RequireAuth>} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
