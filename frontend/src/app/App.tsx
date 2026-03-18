import { Suspense } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

function Loading() {
  const { t } = useTranslation();
  return (
    <div className="flex h-screen items-center justify-center">
      <p className="text-neutral-500">{t('common.loading')}</p>
    </div>
  );
}

function Dashboard() {
  const { t } = useTranslation();
  return (
    <div className="p-8">
      <h1 className="text-2xl font-semibold">{t('app.name')}</h1>
      <p className="mt-2 text-neutral-600">{t('app.tagline')}</p>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
