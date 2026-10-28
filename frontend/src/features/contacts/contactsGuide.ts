// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// contactsGuide - "How it works" content for the Contacts directory module.
// Consumed by <ModuleGuideButton content={contactsGuide} /> on ContactsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const contactsGuide: ModuleGuideContent = {
  titleKey: 'guide.contacts.title',
  titleDefault: 'Contacts',
  introKey: 'guide.contacts.intro',
  introDefault:
    'The Contacts directory is the single address book for every organisation and person on your projects. Capture each party once here and the same record is reused across the platform, so you never key the same company in twice or chase a duplicate.',
  sections: [
    {
      icon: 'Database',
      titleKey: 'guide.contacts.directory.title',
      titleDefault: 'One directory for every party',
      bodyKey: 'guide.contacts.directory.body',
      bodyDefault:
        'Each entry is a company or a person, sorted by type: client, subcontractor, supplier, consultant, internal, lead or customer. A card shows the name, contact type, email, phone, country and prequalification status at a glance, and the same record flows downstream as RFI ball-in-court, transmittal recipient, correspondence party and tender invitee.',
    },
    {
      icon: 'PencilLine',
      titleKey: 'guide.contacts.add.title',
      titleDefault: 'Add and edit a contact',
      bodyKey: 'guide.contacts.add.body',
      bodyDefault:
        'Click New Contact, pick a type, then fill in the company and person details, email, phone, website, country and address. Company name or a contact name is required and the country is a two-letter ISO code. Click any card to reopen it and edit the same fields.',
    },
    {
      icon: 'ClipboardCheck',
      titleKey: 'guide.contacts.prequal.title',
      titleDefault: 'Prequalification and payment terms',
      bodyKey: 'guide.contacts.prequal.body',
      bodyDefault:
        'Set a prequalification status to record who is cleared to bid or be awarded work: Approved is cleared, Pending is under review, Rejected is not eligible and Expired means the qualification lapsed. Payment terms are captured in days, with quick presets of 30, 45 and 60 or any custom value.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.contacts.filter.title',
      titleDefault: 'Search, filter and quick-tag chips',
      bodyKey: 'guide.contacts.filter.body',
      bodyDefault:
        'Search by name or email and narrow the list with the contact-type and country filters. The quick-filter chip strip pivots the directory by tier, topic, language, country, inbox or consent tag, and selecting two chips returns only contacts that carry both.',
    },
    {
      icon: 'Send',
      titleKey: 'guide.contacts.import.title',
      titleDefault: 'Import and export in bulk',
      bodyKey: 'guide.contacts.import.body',
      bodyDefault:
        'Click Import to bring in an Excel or CSV file, using Download import template to match the expected columns; the result reports how many rows were imported, skipped or errored. Export downloads the whole directory back out as an Excel file.',
    },
    {
      icon: 'Workflow',
      titleKey: 'guide.contacts.linked.title',
      titleDefault: 'Linked records and conversion',
      bodyKey: 'guide.contacts.linked.body',
      bodyDefault:
        'Open the actions menu on a card to see records linked to that contact and to act on them. When the Property Development module is enabled you can convert a contact into a lead in one click, or continue into Property Development to create a buyer, with the new record keeping a link back to this contact.',
    },
  ],
  ctaKey: 'guide.contacts.cta',
  ctaDefault: 'Add your first contact',
};
