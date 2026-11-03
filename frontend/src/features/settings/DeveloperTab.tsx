// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Settings, Developer: the two cards a partner integration needs, API keys and signed webhooks. */
import { ApiKeysCard } from './developer/ApiKeysCard';
import { WebhooksCard } from './developer/WebhooksCard';

export default function DeveloperTab() {
  return (
    <div className="space-y-6">
      <ApiKeysCard />
      <WebhooksCard />
    </div>
  );
}
