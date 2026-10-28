// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PortGlyph>` — the small shape-coded glyph for a port's data type.
 *
 * Shared single source so the node port rows, the legend, and any future
 * surface all draw the identical mark (color + shape = not color alone, so it
 * stays color-blind safe). Geometry comes from `tokens.PORT_SHAPE_SVG`.
 */
import { getPortTokens, PORT_SHAPE_SVG } from '../tokens';

export interface PortGlyphProps {
  type: string;
  size?: number;
}

export function PortGlyph({ type, size = 12 }: PortGlyphProps) {
  const tok = getPortTokens(type);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 12 12"
      aria-hidden="true"
      className="shrink-0"
      style={{ fill: tok.color, stroke: tok.color }}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: PORT_SHAPE_SVG[tok.shape] }}
    />
  );
}

export default PortGlyph;
