import type { components } from '../../../api/schema';

export type Product = components['schemas']['Product'];
export type Group = components['schemas']['ConsumerGroup'];

export interface Rail {
  id: number;
  rowIndex: number;
  capacity: number;
}

/** A device on a DIN rail (railId + start, in modules) or on the mounting panel (x/y/w/h, mm). */
export interface Device {
  /** Client-side key. Persisted devices use `s<serverId>`, new ones `n<seq>`. */
  id: string;
  serverId: number | null;
  productId: number;
  railId: number | null;
  start: number | null;
  width: number;
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
  groupId: number | null;
  label: string;
}

export interface PanelModel {
  id: number;
  name: string;
  kind: string;
  enclosureId: number | null;
  ip: number;
  rails: Rail[];
  /** Mounting panel size, mm (null: enclosure has none). */
  area: { width: number | null; height: number | null };
  devices: Device[];
}

export type IssueCode =
  | 'out_of_bounds'
  | 'collision'
  | 'width_mismatch'
  | 'non_din_on_rail'
  | 'din_off_rail'
  | 'unknown_rail'
  | 'not_placeable'
  | 'missing_geometry'
  | 'no_mounting_panel';

export interface Issue {
  code: IssueCode;
  deviceId: string;
  otherId?: string;
}

/** Where a device should go. */
export type Target =
  | { kind: 'rail'; panelId: number; railId: number; start: number }
  | { kind: 'mount'; panelId: number; x: number; y: number };
