// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// signingGuide - "How it works" content for the E-Signature Registry.
// Consumed by <ModuleGuideButton content={signingGuide} /> on SigningPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const signingGuide: ModuleGuideContent = {
  titleKey: 'guide.signing.title',
  titleDefault: 'E-Signature Registry',
  introKey: 'guide.signing.intro',
  introDefault:
    'A jurisdiction-neutral log of who must sign a document, who signed or declined, and whether their signature still matches the current content. It performs no cryptography and stores no keys or passwords - regional signing schemes plug in behind it.',
  sections: [
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.signing.what.title',
      titleDefault: 'What a session tracks',
      bodyKey: 'guide.signing.what.body',
      bodyDefault:
        'A signing session names one document (by reference and content hash), the capability it needs - qualified, advanced or simple electronic, or a digital certificate - and the list of required signatories. It never names a commercial signing provider; capability is a legal tier, not a brand.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.signing.attest.title',
      titleDefault: 'Attest or decline',
      bodyKey: 'guide.signing.attest.body',
      bodyDefault:
        'Each signatory records an attestation - the content hash they actually signed, and optional certificate metadata such as the subject and its valid-until date - or declines with a reason. The session status is derived automatically from these records, not set by hand.',
    },
    {
      icon: 'Lightbulb',
      titleKey: 'guide.signing.stale.title',
      titleDefault: 'Staleness and expiry',
      bodyKey: 'guide.signing.stale.body',
      bodyDefault:
        'If a document is reissued with a new content hash, any signature made against the old hash shows as stale - that signatory needs to re-sign. The certificate panel separately flags recorded certificate metadata that has expired or is expiring soon.',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.signing.manifest.title',
      titleDefault: 'The manifest',
      bodyKey: 'guide.signing.manifest.body',
      bodyDefault:
        'Every session exposes a manifest: the issued document reference paired with its content hash and every recorded signature hash. Download it as evidence that a given signed set matches what was issued.',
    },
  ],
};
