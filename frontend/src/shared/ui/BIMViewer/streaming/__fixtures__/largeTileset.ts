// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tile statistics from a real baked tileset, used to gate streaming order.
 *
 * Source: a 25516 mesh model baked by the octree tiler into
 * 80 tiles totalling 204.0 MB (monolithic GLB 281.9 MB).
 * Only the four fields the streaming comparator reads are kept; the node
 * name lists and hashes are dropped so the fixture stays small.
 *
 * The point of the fixture is the SHAPE of a real building: tile payloads
 * span 1.5 KB to 17 MB and geometry density varies by three orders of
 * magnitude, which is what makes the streaming order matter at all. A
 * synthetic even spread would hide the problem completely.
 */

import type { TileInfo } from '../tileTypes';

/** The subset of TileInfo that tile ordering depends on. */
export interface TileStat {
  id: string;
  node_count: number;
  byte_size: number;
  center: [number, number, number];
}

/**
 * Widen a recorded stat into a full TileInfo, filling the fields the ordering
 * comparator does not read.
 *
 * Deliberately a real function and not a cast: a bare `as unknown as TileInfo[]`
 * would let a newly required field on TileInfo arrive as undefined here while
 * the regression tests kept passing, which is exactly the kind of silent decay
 * this fixture exists to prevent.
 */
export function toTileInfo(stat: TileStat): TileInfo {
  return {
    id: stat.id,
    hash: `hash-${stat.id}`,
    bbox: [...stat.center, ...stat.center],
    center: stat.center,
    radius: 1,
    node_count: stat.node_count,
    byte_size: stat.byte_size,
    nodes: [],
  };
}

export const LARGE_TILESET: TileStat[] = [
  { id: 't0', node_count: 786, byte_size: 2982268, center: [55.962, -43.531, 15.005] },
  { id: 't1', node_count: 53, byte_size: 93764, center: [44.658, -34.112, 24.55] },
  { id: 't2', node_count: 65, byte_size: 126804, center: [44.66, -34.112, 30.695] },
  { id: 't3', node_count: 123, byte_size: 702448, center: [55.562, -48.306, 24.685] },
  { id: 't4', node_count: 90, byte_size: 272972, center: [59.686, -50.085, 30.83] },
  { id: 't5', node_count: 569, byte_size: 5151096, center: [54.25, -39.163, 24.565] },
  { id: 't6', node_count: 558, byte_size: 5096044, center: [55.255, -39.223, 30.823] },
  { id: 't7', node_count: 804, byte_size: 5039972, center: [54.298, -41.852, 36.713] },
  { id: 't8', node_count: 137, byte_size: 554624, center: [44.494, -29.141, 24.575] },
  { id: 't9', node_count: 191, byte_size: 947444, center: [44.523, -29.136, 30.747] },
  { id: 't10', node_count: 524, byte_size: 4755608, center: [59.7, -27.053, 24.63] },
  { id: 't11', node_count: 882, byte_size: 7237544, center: [51.243, -28.979, 31.0] },
  { id: 't12', node_count: 67, byte_size: 2282616, center: [54.82, -21.851, 24.738] },
  { id: 't13', node_count: 105, byte_size: 3796360, center: [53.221, -21.635, 30.71] },
  { id: 't14', node_count: 224, byte_size: 730992, center: [44.462, -29.141, 36.218] },
  { id: 't15', node_count: 22, byte_size: 111260, center: [45.914, -28.627, 40.442] },
  { id: 't16', node_count: 837, byte_size: 5462932, center: [55.678, -28.858, 36.985] },
  { id: 't17', node_count: 224, byte_size: 1245884, center: [56.202, -31.299, 41.578] },
  { id: 't18', node_count: 118, byte_size: 3347520, center: [53.327, -22.452, 37.106] },
  { id: 't19', node_count: 17, byte_size: 81100, center: [52.386, -22.806, 40.442] },
  { id: 't20', node_count: 219, byte_size: 1672260, center: [78.116, -72.394, 10.783] },
  { id: 't21', node_count: 13, byte_size: 613436, center: [74.24, -84.564, 22.24] },
  { id: 't22', node_count: 12, byte_size: 26844, center: [71.667, -67.181, 26.215] },
  { id: 't23', node_count: 18, byte_size: 46612, center: [71.667, -67.181, 30.648] },
  { id: 't24', node_count: 479, byte_size: 2613000, center: [69.613, -61.576, 24.655] },
  { id: 't25', node_count: 528, byte_size: 3270784, center: [70.635, -61.844, 29.832] },
  { id: 't26', node_count: 2, byte_size: 3196, center: [74.116, -68.142, 22.05] },
  { id: 't27', node_count: 113, byte_size: 2867368, center: [76.131, -60.712, 24.685] },
  { id: 't28', node_count: 280, byte_size: 3434996, center: [76.877, -60.712, 31.135] },
  { id: 't29', node_count: 702, byte_size: 3600888, center: [72.982, -61.38, 37.052] },
  { id: 't30', node_count: 3, byte_size: 5120, center: [97.782, -68.061, 26.363] },
  { id: 't31', node_count: 198, byte_size: 504284, center: [70.581, -43.93, 9.8] },
  { id: 't32', node_count: 54, byte_size: 1225416, center: [60.106, -55.846, 11.433] },
  { id: 't33', node_count: 243, byte_size: 1723944, center: [69.351, -46.26, 18.64] },
  { id: 't34', node_count: 143, byte_size: 588132, center: [70.581, -43.93, 12.66] },
  { id: 't35', node_count: 468, byte_size: 2996584, center: [64.35, -44.637, 19.041] },
  { id: 't36', node_count: 26, byte_size: 36864, center: [80.086, -49.269, 12.125] },
  { id: 't37', node_count: 85, byte_size: 187852, center: [80.689, -51.018, 18.64] },
  { id: 't38', node_count: 81, byte_size: 372744, center: [82.206, -36.176, 12.679] },
  { id: 't39', node_count: 316, byte_size: 1767044, center: [78.396, -39.297, 18.58] },
  { id: 't40', node_count: 45, byte_size: 64708, center: [70.37, -32.843, 9.99] },
  { id: 't41', node_count: 588, byte_size: 2543420, center: [70.237, -31.532, 15.829] },
  { id: 't42', node_count: 7, byte_size: 9924, center: [91.232, -44.325, 10.475] },
  { id: 't43', node_count: 139, byte_size: 423192, center: [93.586, -42.251, 16.231] },
  { id: 't44', node_count: 1, byte_size: 1492, center: [87.621, -33.058, 10.075] },
  { id: 't45', node_count: 32, byte_size: 60240, center: [87.621, -33.058, 16.525] },
  { id: 't46', node_count: 790, byte_size: 5928592, center: [63.475, -51.079, 24.655] },
  { id: 't47', node_count: 729, byte_size: 6737548, center: [66.612, -47.358, 31.0] },
  { id: 't48', node_count: 891, byte_size: 5730284, center: [68.673, -43.279, 24.92] },
  { id: 't49', node_count: 826, byte_size: 5839940, center: [68.475, -43.151, 30.965] },
  { id: 't50', node_count: 550, byte_size: 7691836, center: [81.136, -53.301, 24.575] },
  { id: 't51', node_count: 680, byte_size: 9159164, center: [82.718, -49.563, 31.0] },
  { id: 't52', node_count: 599, byte_size: 3736712, center: [77.602, -43.456, 24.655] },
  { id: 't53', node_count: 533, byte_size: 3069008, center: [78.038, -38.94, 31.0] },
  { id: 't54', node_count: 517, byte_size: 3126836, center: [67.024, -47.677, 36.95] },
  { id: 't55', node_count: 140, byte_size: 741388, center: [66.779, -49.093, 42.028] },
  { id: 't56', node_count: 875, byte_size: 6969976, center: [68.525, -43.195, 36.365] },
  { id: 't57', node_count: 405, byte_size: 3138764, center: [64.843, -37.74, 41.694] },
  { id: 't58', node_count: 653, byte_size: 12561912, center: [82.017, -48.304, 37.366] },
  { id: 't59', node_count: 168, byte_size: 840940, center: [78.06, -50.455, 40.743] },
  { id: 't60', node_count: 546, byte_size: 2842400, center: [79.424, -42.429, 37.16] },
  { id: 't61', node_count: 102, byte_size: 478108, center: [77.816, -39.949, 42.285] },
  { id: 't62', node_count: 652, byte_size: 6241040, center: [61.256, -27.831, 24.555] },
  { id: 't63', node_count: 924, byte_size: 7842484, center: [62.755, -27.718, 31.0] },
  { id: 't64', node_count: 203, byte_size: 2640332, center: [64.978, -20.759, 24.63] },
  { id: 't65', node_count: 320, byte_size: 4595364, center: [64.767, -20.753, 30.75] },
  { id: 't66', node_count: 153, byte_size: 739984, center: [82.278, -28.743, 24.63] },
  { id: 't67', node_count: 167, byte_size: 681624, center: [76.879, -27.003, 30.833] },
  { id: 't68', node_count: 13, byte_size: 28496, center: [74.012, -20.489, 24.608] },
  { id: 't69', node_count: 18, byte_size: 47120, center: [74.012, -20.489, 30.89] },
  { id: 't70', node_count: 994, byte_size: 6463924, center: [62.756, -26.959, 37.049] },
  { id: 't71', node_count: 263, byte_size: 2360608, center: [61.423, -28.563, 41.662] },
  { id: 't72', node_count: 298, byte_size: 3235000, center: [64.765, -21.084, 37.039] },
  { id: 't73', node_count: 74, byte_size: 399064, center: [68.432, -21.427, 40.23] },
  { id: 't74', node_count: 206, byte_size: 797616, center: [75.955, -27.114, 37.085] },
  { id: 't75', node_count: 91, byte_size: 343232, center: [75.265, -26.741, 40.565] },
  { id: 't76', node_count: 56, byte_size: 244708, center: [74.046, -20.706, 37.035] },
  { id: 't77', node_count: 26, byte_size: 61500, center: [75.573, -21.088, 39.832] },
  { id: 't78', node_count: 626, byte_size: 17045228, center: [88.314, -48.628, 27.553] },
  { id: 't79', node_count: 237, byte_size: 866156, center: [89.266, -46.541, 36.105] },
];
