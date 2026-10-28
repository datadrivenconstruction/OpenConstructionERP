// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Drop-in toolbar for the Asset Register: "Discover assets" + "Warranty
 * alerts". Sits above the register list. Keeps the discovery modal state
 * local so the host page only has to render the toolbar and (optionally)
 * react to ``onChanged`` to refetch its list after a bulk promotion.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Sparkles } from 'lucide-react';

import { Button } from '@/shared/ui';

import { DiscoverAssetsModal } from './DiscoverAssetsModal';
import { WarrantyAlertsButton } from './WarrantyAlertsButton';

interface AssetOperationsToolbarProps {
  projectId: string;
  onChanged?: () => void;
}

export function AssetOperationsToolbar({ projectId, onChanged }: AssetOperationsToolbarProps) {
  const { t } = useTranslation();
  const [discovering, setDiscovering] = useState(false);

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="asset-ops-toolbar">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => setDiscovering(true)}
        data-testid="discover-assets-open"
      >
        <Sparkles size={14} className="mr-1" />
        {t('assets.discover.open', { defaultValue: 'Discover assets' })}
      </Button>
      <WarrantyAlertsButton projectId={projectId} />

      {discovering && (
        <DiscoverAssetsModal
          projectId={projectId}
          onClose={() => setDiscovering(false)}
          onPromoted={(count) => {
            setDiscovering(false);
            if (count > 0) onChanged?.();
          }}
        />
      )}
    </div>
  );
}

export default AssetOperationsToolbar;
