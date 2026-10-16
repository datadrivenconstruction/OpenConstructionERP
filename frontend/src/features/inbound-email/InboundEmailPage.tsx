// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inbound Email page.
 *
 * The explainer sits at page level, above the working area, so it stays
 * findable rather than disappearing with whatever is open.
 */

import { useTranslation } from 'react-i18next';
import { Inbox } from 'lucide-react';

import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';

import { InboundEmailPanel } from './InboundEmailPanel';

export function InboundEmailPage() {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <CollapsibleSection
        storageKey="inbound_email.how"
        icon={<Inbox size={15} className="text-oe-blue" />}
        title={t('inbound_email.flow_title', {
          defaultValue: 'Reading a message for what it says about delay',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('inbound_email.flow_intro', {
            defaultValue:
              'Most of what a project knows about a delay is written in correspondence long before anyone builds a claim out of it. This module reads one exported message and tells you which delay categories it touches and which phrases said so.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('inbound_email.flow_step1', {
              defaultValue:
                'Export the message from your mail client as a file and drop it here. This is a file import, not a mailbox connection, so nothing is fetched on your behalf.',
            })}
          </li>
          <li>
            {t('inbound_email.flow_step2', {
              defaultValue:
                'The message is normalised into a record: subject, sender, recipients, the threading ids that place it in a conversation, the text body and the attachment names and sizes.',
            })}
          </li>
          <li>
            {t('inbound_email.flow_step3', {
              defaultValue:
                'The text is scanned for the phrases each delay category is known by, and every match is shown, so a confidence can be checked against the words that produced it.',
            })}
          </li>
          <li>
            {t('inbound_email.flow_step4', {
              defaultValue:
                'Each category carries a short starter fragnet, the activities a planner would normally add to the programme for that kind of event. Take what fits and leave the rest.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('inbound_email.flow_links', {
            defaultValue:
              'Nothing here is stored. To file correspondence against a project use Correspondence, and to receive it automatically use the Inbound Capture gateway; what a delay eventually becomes is argued in Claims Evidence and planned in Schedule.',
          })}
        </p>
      </CollapsibleSection>

      <InboundEmailPanel />
    </div>
  );
}
