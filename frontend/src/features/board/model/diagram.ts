import { shortName } from './match';
import type { Device, Group, PanelModel, Product } from './types';

export type NodeKind = 'feeder' | 'chain' | 'bus' | 'rcd' | 'breaker' | 'other';

export interface DiagramNode {
  /** `feeder`, `bus` or the device id. */
  id: string;
  kind: NodeKind;
  /** Device designation (QF3, QD1 …); empty for feeder/bus. */
  tag: string;
  title: string;
  subtitle: string;
  /** Third line: load description of a bound group. */
  load: string;
  deviceId: string | null;
  groupId: number | null;
  x: number;
  y: number;
}

export interface DiagramEdge {
  id: string;
  source: string;
  target: string;
}

export interface Diagram {
  nodes: DiagramNode[];
  edges: DiagramEdge[];
}

export const NODE_W = 170;
export const COL_GAP = 20;
export const ROW_H = 96;

const INPUT = new Set(['main_switch', 'meter', 'voltage_relay', 'phase_relay', 'spd']);
const PREFIX: Record<string, string> = {
  main_switch: 'QS',
  mcb: 'QF',
  rcd: 'QD',
  rcbo: 'QFD',
  spd: 'FV',
  voltage_relay: 'KV',
  phase_relay: 'KV',
  meter: 'PI',
  contactor: 'KM',
  timer: 'KT',
  ats: 'KM',
};

function isFireRcd(p: Product | undefined): boolean {
  return p?.category.code === 'rcd' && (p.leakage_ma ?? 0) >= 100;
}

/** Devices in reading order: DIN rails top to bottom, left to right; then mounting-panel items. */
export function orderedDevices(panel: PanelModel): Device[] {
  const row = new Map(panel.rails.map((r) => [r.id, r.rowIndex]));
  const din = panel.devices
    .filter((d) => d.railId !== null && d.start !== null)
    .sort(
      (a, b) =>
        (row.get(a.railId as number) ?? 0) - (row.get(b.railId as number) ?? 0) ||
        (a.start as number) - (b.start as number),
    );
  const mount = panel.devices
    .filter((d) => d.railId === null)
    .sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0));
  return [...din, ...mount];
}

/** IEC 81346-style designations numbered per prefix in reading order. */
export function designations(
  panel: PanelModel,
  products: Map<number, Product>,
): Map<string, string> {
  const counters = new Map<string, number>();
  const out = new Map<string, string>();
  for (const d of orderedDevices(panel)) {
    const p = products.get(d.productId);
    const code = p?.category.code ?? '';
    const prefix = isFireRcd(p) ? 'QD' : (PREFIX[code] ?? 'X');
    const n = (counters.get(prefix) ?? 0) + 1;
    counters.set(prefix, n);
    out.set(d.id, `${prefix}${n}`);
  }
  return out;
}

function loadText(g: Group | undefined): string {
  if (!g) return '';
  const cable = g.cable_mm2 ? ` · ${Number(g.cable_mm2)} мм²` : '';
  return `${g.power_w} Вт${cable}`;
}

/**
 * Derive the single-line diagram of a board from its physical layout.
 * Rule (same as autolayout): devices before the first group device form the input chain;
 * a non-fire RCD feeds every breaker after it until the next RCD; RCBOs and breakers before
 * any RCD hang directly off the busbar.
 */
export function buildDiagram(
  panel: PanelModel,
  products: Map<number, Product>,
  groups: Group[],
  positions: PanelModel['diagramPositions'] = panel.diagramPositions,
): Diagram {
  const tags = designations(panel, products);
  const groupById = new Map(groups.map((g) => [g.id, g]));
  const nodes: DiagramNode[] = [];
  const edges: DiagramEdge[] = [];
  const link = (a: string, b: string) => edges.push({ id: `${a}>${b}`, source: a, target: b });

  const make = (d: Device, kind: NodeKind, x: number, y: number): DiagramNode => {
    const p = products.get(d.productId);
    const g = d.groupId !== null ? groupById.get(d.groupId) : undefined;
    return {
      id: d.id,
      kind,
      tag: tags.get(d.id) ?? '',
      title: g?.name ?? (d.label || (p ? shortName(p) : '?')),
      subtitle: p ? `${p.brand.name} ${p.sku}` : '',
      load: loadText(g),
      deviceId: d.id,
      groupId: d.groupId,
      x,
      y,
    };
  };

  const devices = orderedDevices(panel).filter((d) => d.railId !== null);
  const mounted = orderedDevices(panel).filter((d) => d.railId === null);
  const catOf = (d: Device) => products.get(d.productId)?.category.code ?? '';

  // Input chain: switch/meter/relay/SPD/fire RCD and the unbound multi-pole main breaker.
  const isInput = (d: Device): boolean => {
    const p = products.get(d.productId);
    return (
      INPUT.has(catOf(d)) ||
      isFireRcd(p) ||
      (catOf(d) === 'mcb' && d.groupId === null && (p?.poles ?? 1) >= 2)
    );
  };
  let firstGroup = devices.findIndex((d) => !isInput(d));
  if (firstGroup < 0) firstGroup = devices.length;
  const chain = devices.slice(0, firstGroup);
  const rest = devices.slice(firstGroup);

  nodes.push({
    id: 'feeder',
    kind: 'feeder',
    tag: '',
    title: '~ 230/400 В',
    subtitle: panel.name,
    load: '',
    deviceId: null,
    groupId: null,
    x: 0,
    y: 0,
  });
  let prev = 'feeder';
  chain.forEach((d, i) => {
    nodes.push(make(d, 'chain', (i + 1) * (NODE_W + COL_GAP), 0));
    link(prev, d.id);
    prev = d.id;
  });
  const busX = (chain.length + 1) * (NODE_W + COL_GAP);
  nodes.push({
    id: 'bus',
    kind: 'bus',
    tag: '',
    title: 'N / PE · L',
    subtitle: '',
    load: '',
    deviceId: null,
    groupId: null,
    x: busX,
    y: 0,
  });
  link(prev, 'bus');

  let col = chain.length + 1;
  let currentRcd: string | null = null;
  let rcdRow = 0;
  const colX = (c: number) => c * (NODE_W + COL_GAP);
  for (const d of rest) {
    const code = catOf(d);
    if (code === 'rcd') {
      currentRcd = d.id;
      rcdRow = 0;
      nodes.push(make(d, 'rcd', colX(col), ROW_H));
      link('bus', d.id);
      col += 1;
    } else if (code === 'mcb' && currentRcd !== null) {
      rcdRow += 1;
      const parent = nodes.find((n) => n.id === currentRcd) as DiagramNode;
      nodes.push(make(d, 'breaker', parent.x, ROW_H * (1 + rcdRow)));
      link(currentRcd, d.id);
    } else if (code === 'mcb' || code === 'rcbo') {
      currentRcd = null;
      nodes.push(make(d, 'breaker', colX(col), ROW_H));
      link('bus', d.id);
      col += 1;
    } else {
      nodes.push(make(d, 'other', colX(col), ROW_H));
      link('bus', d.id);
      col += 1;
    }
  }
  for (const d of mounted) {
    nodes.push(make(d, 'other', colX(col), ROW_H));
    link('bus', d.id);
    col += 1;
  }
  for (const n of nodes) {
    const o = positions[n.id];
    if (o) {
      n.x = o.x;
      n.y = o.y;
    }
  }
  return { nodes, edges };
}
