import { Suspense, useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AppLayout } from './layout';
import { DashboardPage } from '@/features/dashboard';
import { LoginPage } from '@/features/auth';
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
          <span className="text-xl">🚧</span>
        </div>
        <h2 className="text-xl font-semibold text-content-primary">{t(titleKey)}</h2>
        <p className="mt-2 text-sm text-content-secondary">Coming in Phase 1</p>
      </div>
    </AppLayout>
  );
}

export default function App() {
  const loadFromStorage = useAuthStore((s) => s.loadFromStorage);

  useEffect(() => {
    loadFromStorage();
  }, [loadFromStorage]);

  return (
    <Suspense fallback={<LoadingScreen />}>
      <Routes>
        {/* Auth */}
        <Route path="/login" element={<LoginPage />} />

        {/* App */}
        <Route
          path="/"
          element={
            <AppLayout title="Dashboard">
              <DashboardPage />
            </AppLayout>
          }
        />
        <Route path="/projects" element={<PlaceholderPage titleKey="projects.title" />} />
        <Route path="/boq" element={<PlaceholderPage titleKey="boq.title" />} />
        <Route path="/takeoff" element={<PlaceholderPage titleKey="takeoff.title" />} />
        <Route path="/costs" element={<PlaceholderPage titleKey="costs.title" />} />
        <Route path="/validation" element={<PlaceholderPage titleKey="validation.title" />} />
        <Route path="/tendering" element={<PlaceholderPage titleKey="tendering.title" />} />
        <Route path="/modules" element={<PlaceholderPage titleKey="modules.title" />} />
        <Route path="/settings" element={<PlaceholderPage titleKey="nav.settings" />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
