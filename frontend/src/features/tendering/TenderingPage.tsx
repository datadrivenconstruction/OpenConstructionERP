import { useTranslation } from 'react-i18next';
import { FileText, Send, BarChart3, Award } from 'lucide-react';
import { Card, EmptyState } from '@/shared/ui';

export function TenderingPage() {
  const { t } = useTranslation();

  const features = [
    { icon: <FileText size={20} />, title: 'Generate Tender Documents', desc: 'Create GAEB X83, PDF, or Excel tender packages from your BOQ' },
    { icon: <Send size={20} />, title: 'Distribute to Subcontractors', desc: 'Send tender invitations and track responses' },
    { icon: <BarChart3 size={20} />, title: 'Compare Bids', desc: 'Side-by-side bid analysis with price spread and coverage' },
    { icon: <Award size={20} />, title: 'Award Recommendation', desc: 'Score bids automatically and generate award letters' },
  ];

  return (
    <div className="max-w-content mx-auto">
      <div className="mb-6 animate-card-in" style={{ animationDelay: '0ms' }}>
        <h1 className="text-2xl font-bold text-content-primary">{t('tendering.title', 'Tendering')}</h1>
        <p className="mt-1 text-sm text-content-secondary">
          Manage bid packages, collect and compare subcontractor offers
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {features.map((f, i) => (
          <Card
            key={f.title}
            hoverable
            className="animate-card-in cursor-pointer"
            style={{ animationDelay: `${100 + i * 80}ms` }}
          >
            <div className="flex items-start gap-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                {f.icon}
              </div>
              <div>
                <h3 className="text-sm font-semibold text-content-primary">{f.title}</h3>
                <p className="mt-1 text-xs text-content-secondary">{f.desc}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-8 animate-card-in" style={{ animationDelay: '500ms' }}>
        <EmptyState
          icon={<FileText size={24} strokeWidth={1.5} />}
          title="Tendering module coming in Phase 4"
          description="The full tendering workflow will include GAEB export, bid collection, comparison matrices, and automated scoring."
        />
      </div>
    </div>
  );
}
