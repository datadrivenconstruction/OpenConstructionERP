// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Attached and measurable for WebGL, without extending either scroll edge. */
export function createStreetThumbnailContainer(width: number, height: number) {
  const host = document.createElement('div');
  host.setAttribute('aria-hidden', 'true');
  Object.assign(host.style, {
    position: 'fixed', left: '0', top: '0', width: '1px', height: '1px',
    overflow: 'hidden', opacity: '0', pointerEvents: 'none',
  });
  const container = document.createElement('div');
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
  host.appendChild(container);
  document.body.appendChild(host);
  return { host, container };
}
