// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// buyerPortalGuide - "How it works" content for the Buyer Portal module.
// Consumed by <ModuleGuideButton content={buyerPortalGuide} /> in the
// BuyerPortalPage header.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const buyerPortalGuide: ModuleGuideContent = {
  titleKey: 'guide.buyer_portal.title',
  titleDefault: 'Buyer Portal',
  introKey: 'guide.buyer_portal.intro',
  introDefault:
    'The buyer portal is your private, password-free dashboard for the home you are purchasing. Open it from the secure link your sales agent emails you to track your reservation, see what you owe, download signed paperwork and send documents back.',
  sections: [
    {
      icon: 'BookOpen',
      titleKey: 'guide.buyer_portal.overview.title',
      titleDefault: 'Your purchase at a glance',
      bodyKey: 'guide.buyer_portal.overview.body',
      bodyDefault:
        'The welcome screen greets you by name and shows the development, your reservation number and plot. Quick-link tiles jump straight to payments, document uploads, your files and the contact form, with the most urgent action highlighted first.',
      spotlightSelector: '[data-testid="welcome-hero"]',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.buyer_portal.reservation.title',
      titleDefault: 'Reservation and contract',
      bodyKey: 'guide.buyer_portal.reservation.body',
      bodyDefault:
        'The reservation card lists your plot, address, deposit and current status, and the Sale and Purchase Agreement card shows the contract number, total value and where it stands. These are read-only summaries kept in step with your sales agent.',
      spotlightSelector: '[data-testid="reservation-card"]',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.buyer_portal.payments.title',
      titleDefault: 'Payment schedule',
      bodyKey: 'guide.buyer_portal.payments.body',
      bodyDefault:
        'The payment schedule breaks your price into milestone instalments with due dates, amounts and what has been paid. A progress bar shows how much of the total is settled, and tapping any milestone opens its full detail. To pay or get a receipt, message your agent.',
      spotlightSelector: '[data-testid="payments-section"]',
    },
    {
      icon: 'FileSearch',
      titleKey: 'guide.buyer_portal.documents.title',
      titleDefault: 'Your documents library',
      bodyKey: 'guide.buyer_portal.documents.body',
      bodyDefault:
        'Every signed document shared with you, such as contracts and invoices, is grouped by type with its delivery date. Open or download any file at any time. The library fills up as your agent issues new paperwork.',
      spotlightSelector: '[data-testid="documents-section"]',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.buyer_portal.kyc.title',
      titleDefault: 'Upload the documents we need',
      bodyKey: 'guide.buyer_portal.kyc.body',
      bodyDefault:
        'When identity or compliance documents are requested, each one gets its own upload box. Drag and drop files on a computer or tap to choose, or use your phone camera to photograph a passport or ID. Stage several files, then upload them all and the request turns green once received.',
      spotlightSelector: '[data-testid="kyc-section"]',
    },
    {
      icon: 'Send',
      titleKey: 'guide.buyer_portal.contact.title',
      titleDefault: 'Contact your agent',
      bodyKey: 'guide.buyer_portal.contact.body',
      bodyDefault:
        'Have a question or need an update? Send a message straight to your assigned sales agent from the contact form, and add a callback number if you would like a phone reply. Your agent receives it and gets back to you.',
      spotlightSelector: '[data-testid="contact-section"]',
    },
  ],
  ctaKey: 'guide.buyer_portal.cta',
  ctaDefault: 'Review your purchase',
};
