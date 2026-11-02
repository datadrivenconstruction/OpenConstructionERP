// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// One saved before/after pair, full width, with a link back to the archive.

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { ErrorState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchCompare, photosKeys } from './api';
import { BeforeAfterSlider } from './components/BeforeAfterSlider';

export function PhotoComparePage() {
  const { t } = useTranslation();
  const { compareId = '' } = useParams();
  const cmp = useQuery({ queryKey: photosKeys.compare(compareId), queryFn: () => fetchCompare(compareId), enabled: Boolean(compareId) });

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <PageHeader
        srTitle={t('photoArchive.compare.title')}
        subtitle={cmp.data?.title || t('photoArchive.compare.subtitle')}
        actions={
          <Link to="/photos?view=compare" className="inline-flex items-center gap-1 text-sm text-oe-blue hover:underline">
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t('photoArchive.compare.back')}
          </Link>
        }
      />
      {cmp.isLoading ? (
        <Loader2 className="mx-auto h-6 w-6 animate-spin text-content-tertiary" aria-hidden />
      ) : cmp.isError || !cmp.data ? (
        <ErrorState title={t('photoArchive.compare.load_failed')} hint={getErrorMessage(cmp.error)} onRetry={() => cmp.refetch()} />
      ) : (
        <BeforeAfterSlider before={cmp.data.before} after={cmp.data.after} />
      )}
    </div>
  );
}

export default PhotoComparePage;
