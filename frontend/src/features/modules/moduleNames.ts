import { MODULE_REGISTRY } from '@/modules/_registry';
import { translateManifestText, type Translate } from '@/modules/_i18n';

/** Module ids as the person reads them (the manifest's own name), not as the registry keys them. */
export function moduleNames(t: Translate, ids: string[]): string[] {
  return ids.map((id) => {
    const m = MODULE_REGISTRY.find((x) => x.id === id);
    return m ? translateManifestText(t, m.name) : id;
  });
}
