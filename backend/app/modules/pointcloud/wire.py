# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Binary wire format for streaming decimated points to the browser.

One self-describing little-endian buffer the frontend reads in a single pass
and feeds straight into typed-array geometry attributes - no per-point JSON, no
base64. Layout:

    offset  type        field
    0       char[4]     magic "OEPC"
    4       uint32      version (1)
    8       uint32      point_count N
    12      uint32      flags  bit0 = has RGB, bit1 = has intensity
    16      float64[3]  center (world origin subtracted from positions)
    40      float32[6]  bbox in world frame: minx,miny,minz,maxx,maxy,maxz
    64      float32[3N] positions, centre-relative, XYZ interleaved
    ...     uint8[3N]   RGB interleaved          (only if flags bit0)
    ...     float32[N]  intensity 0-1            (only if flags bit1)

The frontend mirrors this in ``parsePointBuffer``.
"""

from __future__ import annotations

import struct

import numpy as np

from app.modules.pointcloud.decode import DecodedPoints

_MAGIC = b"OEPC"
_VERSION = 1
_FLAG_RGB = 1 << 0
_FLAG_INTENSITY = 1 << 1
_HEADER_STRUCT = struct.Struct("<4sIII3d6f")


def pack_points(points: DecodedPoints) -> bytes:
    """Serialise a decoded payload into the OEPC binary buffer."""
    n = points.returned_count
    flags = 0
    if points.rgb is not None:
        flags |= _FLAG_RGB
    if points.intensity is not None:
        flags |= _FLAG_INTENSITY

    header = _HEADER_STRUCT.pack(
        _MAGIC,
        _VERSION,
        n,
        flags,
        points.center[0],
        points.center[1],
        points.center[2],
        points.bbox_min[0],
        points.bbox_min[1],
        points.bbox_min[2],
        points.bbox_max[0],
        points.bbox_max[1],
        points.bbox_max[2],
    )

    parts = [header, np.ascontiguousarray(points.xyz, dtype="<f4").tobytes()]
    if points.rgb is not None:
        parts.append(np.ascontiguousarray(points.rgb, dtype=np.uint8).tobytes())
    if points.intensity is not None:
        parts.append(np.ascontiguousarray(points.intensity, dtype="<f4").tobytes())
    return b"".join(parts)
