// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Onboarding step "Choose your packages". Installing hands the resolved module
 * list back to the wizard, so its Modules and Finish steps continue from it.
 */
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { useSolutionPackages } from './api';
import { PackagePicker } from './PackagePicker';

export function StepSolutionPackages({
  onInstalled,
  onUseProfiles,
  onBack,
}: {
  onInstalled: (enabledModules: string[]) => void;
  onUseProfiles: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useSolutionPackages();

  return (
    <div className="space-y-4" data-testid="step-solution-packages">
      <div>
        <h2 className="text-xl font-bold text-content-primary">{t('packages.step_title', { defaultValue: 'Choose your packages' })}</h2>
        <p className="mt-1 text-sm text-content-secondary">{t('packages.step_subtitle', { defaultValue: 'Each package switches on the modules one kind of work needs. Only those show in your menu, and you can add any other module or package later.' })}</p>
      </div>
      {isLoading && <Loader2 className="animate-spin text-oe-blue" aria-label={t('packages.loading', { defaultValue: 'Loading packages' })} />}
      {isError && (
        <p className="text-sm text-content-secondary">{t('packages.load_error', { defaultValue: 'Packages could not be loaded. You can pick a company profile instead.' })}</p>
      )}
      {data && (
        <PackagePicker
          packages={data.packages}
          installed={data.state.installed}
          submitLabel={t('packages.install_continue', { defaultValue: 'Install and continue' })}
          onInstalled={(result) => onInstalled(result.enabled_modules)}
        />
      )}
      <div className="flex items-center justify-between pt-2">
        <button type="button" onClick={onBack} className="text-sm text-content-secondary hover:text-content-primary">
          {t('packages.back', { defaultValue: 'Back' })}
        </button>
        <button type="button" onClick={onUseProfiles} className="text-sm font-semibold text-oe-blue">
          {t('packages.use_profiles', { defaultValue: 'Pick a single company profile instead' })}
        </button>
      </div>
    </div>
  );
}
