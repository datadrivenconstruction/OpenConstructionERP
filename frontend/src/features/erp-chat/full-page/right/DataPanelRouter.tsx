// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { RENDERER_REGISTRY, GenericTableRenderer } from './renderers';

interface DataPanelRouterProps {
  renderer: string;
  data: unknown;
}

export default function DataPanelRouter({ renderer, data }: DataPanelRouterProps) {
  const Component = RENDERER_REGISTRY[renderer] ?? GenericTableRenderer;
  return <Component data={data} />;
}
