// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Send, FileText } from 'lucide-react';
import { Badge, DateDisplay, SideDrawer } from '@/shared/ui';
import { fetchContainerTransmittals, type ContainerTransmittalLink } from './api';

/**
 * Small inline badge: "N transmittals" — clicking it opens a drawer showing
 * every transmittal that carries a revision from the container.
 *
 * Driven by `GET /v1/cde/containers/{id}/transmittals/` (RFC 33 §3.3).
 */
export function CDETransmittalsBadge({
  containerId,
}: {
  containerId: string;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const { data: links = [] } = useQuery({
    queryKey: ['cde-transmittals', containerId],
    queryFn: () => fetchContainerTransmittals(containerId),
    staleTime: 60_000,
  });

  if (links.length === 0) return null;

  return (
    <>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        className="inline-flex items-center gap-1 text-2xs text-oe-blue hover:text-oe-blue/80 font-medium px-1.5 py-0.5 rounded hover:bg-oe-blue/10 transition-colors"
        aria-label={t('cde.transmittals_badge_aria', {
          defaultValue: '{{count}} transmittals linked to this container',
          count: links.length,
        })}
      >
        <Send size={12} />
        {t('cde.transmittals_badge', {
          defaultValue: '{{count}} transmittals',
          count: links.length,
        })}
      </button>

      {open && (
        <TransmittalsDrawer
          links={links}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function TransmittalsDrawer({
  links,
  onClose,
}: {
  links: ContainerTransmittalLink[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <SideDrawer
      open
      onClose={onClose}
      widthClass="max-w-md"
      title={t('cde.transmittals_drawer_title', {
        defaultValue: 'Transmittals carrying this container',
      })}
    >
        <div className="px-5 py-4 space-y-2">
          {links.map((link) => (
            <div
              key={`${link.transmittal_id}-${link.revision_id ?? ''}`}
              className="rounded-lg border border-border p-3 text-sm bg-surface-secondary/40"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="font-mono font-semibold text-content-secondary">
                  {link.transmittal_number}
                </span>
                <Badge variant="blue" size="sm">
                  {t(`transmittals.status_${link.status}`, {
                    defaultValue: link.status,
                  })}
                </Badge>
              </div>
              <p className="text-content-primary truncate">{link.subject}</p>
              <div className="flex items-center gap-2 mt-1 text-xs text-content-tertiary">
                {link.revision_code && (
                  <span className="inline-flex items-center gap-1 font-mono">
                    <FileText size={12} /> {link.revision_code}
                  </span>
                )}
                {link.issued_date && (
                  <DateDisplay value={link.issued_date} className="text-xs" />
                )}
              </div>
            </div>
          ))}
        </div>
    </SideDrawer>
  );
}
