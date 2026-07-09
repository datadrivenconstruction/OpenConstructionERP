/**
 * TypeScript mirror of the ACAP FloorPlan pydantic schema
 * (backend/app/modules/acap/layout/schema.py). Keep in lock-step.
 *
 * Coordinate system: origin (0,0) at the kavling SOUTH-WEST corner,
 * x -> east (0..width_m), y -> north (0..length_m), all in meters.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Kavling {
  width_m: number;
  length_m: number;
}

/** Mirrors ROOM_TYPES in schema.py. */
export type RoomType =
  | 'kamar_tidur_utama'
  | 'kamar_tidur'
  | 'kamar_mandi'
  | 'dapur'
  | 'ruang_tamu'
  | 'ruang_keluarga'
  | 'ruang_makan'
  | 'carport'
  | 'garasi'
  | 'musholla'
  | 'gudang'
  | 'teras'
  | 'taman'
  | 'sirkulasi'
  | 'other';

export interface Room {
  name: string;
  type: RoomType;
  /** EXACTLY 4 corners, axis-aligned rectangle, CCW. Not closed (first point not repeated). */
  polygon: Point[];
  area_m2: number;
}

export interface Wall {
  start: Point;
  end: Point;
  thickness_m: number;
}

export interface Opening {
  type: 'door' | 'window';
  room: string;
  width_m: number;
}

export interface Level {
  level: number;
  rooms: Room[];
  walls: Wall[];
  openings: Opening[];
}

export interface FloorPlan {
  kavling: Kavling;
  levels: Level[];
  requirement_text: string;
  jumlah_lantai: number;
  generated_by: string;
  notes: string;
}
