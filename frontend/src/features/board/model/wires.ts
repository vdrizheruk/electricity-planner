import { buildDiagram } from './diagram';
import { MODULE_PX, RAIL_HEIGHT_PX } from './geometry';
import type { Device, Group, PanelModel, Product } from './types';

/** Vertical space between rails: wiring channel + N and PE busbars. */
export const WIRE_GAP = 44;
export const ROW_PITCH = RAIL_HEIGHT_PX + WIRE_GAP;

export type WireKind = 'L' | 'N' | 'PE';
export type Phase = 'L1' | 'L2' | 'L3';
const PHASES: Phase[] = ['L1', 'L2', 'L3'];

export const WIRE_COLOR: Record<WireKind, string> = {
  L: '#dc2626',
  N: '#2563eb',
  PE: '#eab308',
};
/** IEC 60445 phase colours, used in 3-phase projects. Single-phase projects use red. */
export const PHASE_COLOR: Record<Phase, string> = {
  L1: '#92400e',
  L2: '#111827',
  L3: '#9ca3af',
};
export const PE_STRIPE = '#16a34a';

export interface Pt {
  x: number;
  y: number;
}
export interface Wire {
  id: string;
  kind: WireKind;
  /** Stroke colour. */
  color: string;
  /** Phase of an L wire in a 3-phase project. */
  phase?: Phase;
  points: Pt[];
}
export interface Bar {
  id: string;
  kind: 'N' | 'PE';
  x: number;
  y: number;
  w: number;
}
export interface WireSet {
  wires: Wire[];
  bars: Bar[];
  width: number;
  height: number;
}

const BAR_H = 6;
const N_BAR_DY = 14;
const PE_BAR_DY = 26;
const TERM_MARGIN = 4;
const TRACKS = 3;
const PHASE_STEP = 4;

export function railTop(row: number): number {
  return WIRE_GAP + row * ROW_PITCH;
}

function hasN(p: Product | undefined): boolean {
  if (!p) return false;
  const c = p.category.code;
  return c === 'rcd' || c === 'rcbo' || c === 'voltage_relay' || (p.poles ?? 1) >= 2;
}

/**
 * Wiring of a board in the coordinate system of the rails column (first rail at y = WIRE_GAP).
 * L (phase, red) follows the single-line topology: feeder → input chain → busbar → RCD →
 * breakers. N (blue) goes from the N busbar to every device with a neutral terminal; every
 * outgoing group gets an L/N/PE core fan-out (red/blue/yellow-green). N and PE busbars run
 * under each rail.
 */
export function buildWires(
  panel: PanelModel,
  products: Map<number, Product>,
  groups: Group[],
  threePhase = false,
): WireSet {
  const rails = [...panel.rails].sort((a, b) => a.rowIndex - b.rowIndex);
  const rowOf = new Map(rails.map((r, i) => [r.id, i]));
  const wires: Wire[] = [];
  const bars: Bar[] = [];
  const byId = new Map(panel.devices.map((d) => [d.id, d]));

  const onRail = (d: Device): boolean =>
    d.railId !== null && d.start !== null && rowOf.has(d.railId);
  const left = (d: Device): number => (d.start as number) * MODULE_PX;
  const top = (d: Device): number => railTop(rowOf.get(d.railId as number) as number);
  const inPt = (d: Device): Pt => ({ x: left(d) + TERM_MARGIN, y: top(d) + TERM_MARGIN });
  const outPt = (d: Device): Pt => ({
    x: left(d) + TERM_MARGIN,
    y: top(d) + RAIL_HEIGHT_PX - TERM_MARGIN,
  });

  rails.forEach((r, i) => {
    const y = railTop(i) + RAIL_HEIGHT_PX;
    const w = r.capacity * MODULE_PX;
    bars.push(
      { id: `N${r.id}`, kind: 'N', x: 0, y: y + N_BAR_DY, w },
      { id: `PE${r.id}`, kind: 'PE', x: 0, y: y + PE_BAR_DY, w },
    );
  });
  const nBarY = (d: Device) => top(d) + RAIL_HEIGHT_PX + N_BAR_DY + BAR_H / 2;
  const peBarY = (d: Device) => top(d) + RAIL_HEIGHT_PX + PE_BAR_DY + BAR_H / 2;

  const diagram = buildDiagram(panel, products, groups);
  const trackUse = new Map<number, number>();
  const nextTrack = (row: number): number => {
    const n = trackUse.get(row) ?? 0;
    trackUse.set(row, n + 1);
    return 4 + (n % TRACKS) * 3;
  };

  // The device that feeds the busbar (end of the input chain), if any.
  const busFeed = diagram.edges.find((e) => e.target === 'bus')?.source ?? 'feeder';
  const firstChain = diagram.edges.find((e) => e.source === 'feeder' && e.target !== 'bus')?.target;
  const resolve = (id: string): Device | null => {
    const key = id === 'bus' ? busFeed : id;
    return key === 'feeder' ? null : (byId.get(key) ?? null);
  };

  const childOf = new Map<string, Device>();
  for (const e of diagram.edges) {
    const child = byId.get(e.target);
    if (child && child.groupId !== null && !childOf.has(e.source)) childOf.set(e.source, child);
  }
  const groupOf = new Map(groups.map((g) => [g.id, g]));
  /** Phases carried by a device in a 3-phase project. */
  const phasesOf = (d: Device, depth = 0): Phase[] => {
    const g = d.groupId !== null ? groupOf.get(d.groupId) : undefined;
    if (g && (PHASES as string[]).includes(g.assigned_phase)) return [g.assigned_phase as Phase];
    if (g && g.assigned_phase === '3ph') return PHASES;
    const p = products.get(d.productId);
    if ((p?.poles ?? 1) >= 3) return PHASES;
    const child = childOf.get(d.id);
    if (child && depth < 2) return phasesOf(child, depth + 1).slice(0, 1);
    return ['L1'];
  };

  /** Push the L wire(s) of one connection: one red wire, or one per phase in 3-phase projects. */
  const pushL = (id: string, d: Device | null, pts: (dx: number) => Pt[], phases?: Phase[]) => {
    if (!threePhase) {
      wires.push({ id, kind: 'L', color: WIRE_COLOR.L, points: pts(0) });
      return;
    }
    const list = phases ?? (d ? phasesOf(d) : PHASES);
    list.forEach((ph, i) => {
      wires.push({
        id: `${id}:${ph}`,
        kind: 'L',
        color: PHASE_COLOR[ph],
        phase: ph,
        points: pts(list.length > 1 ? PHASES.indexOf(ph) * PHASE_STEP : i * PHASE_STEP),
      });
    });
  };
  const shift = (pts: Pt[], dx: number): Pt[] => pts.map((q) => ({ x: q.x + dx, y: q.y }));
  const wire = (id: string, kind: 'N' | 'PE', points: Pt[]): void => {
    wires.push({ id, kind, color: WIRE_COLOR[kind], points });
  };

  for (const e of diagram.edges) {
    const b = byId.get(e.target);
    if (!b || !onRail(b)) continue;
    const a = resolve(e.source);
    if (!a) continue; // from feeder: handled below
    if (!onRail(a)) continue;
    const row = rowOf.get(a.railId as number) as number;
    const chY = railTop(row) + RAIL_HEIGHT_PX + nextTrack(row);
    const p = outPt(a);
    const q = inPt(b);
    pushL(`L:${e.id}`, b, (dx) => shift([p, { x: p.x, y: chY }, { x: q.x, y: chY }, q], dx));
  }

  // Feeder entering the first device of the input chain from above.
  const entry = firstChain ? byId.get(firstChain) : undefined;
  const head =
    entry && onRail(entry)
      ? entry
      : (diagram.edges.map((e) => byId.get(e.target)).find((d) => d && onRail(d)) ?? undefined);
  if (head && onRail(head)) {
    const q = inPt(head);
    const nOff = threePhase ? 14 : 7;
    pushL(
      'in:L',
      null,
      (dx) => [
        { x: q.x + dx, y: 4 },
        { x: q.x + dx, y: q.y },
      ],
      PHASES,
    );
    wire('in:N', 'N', [
      { x: q.x + nOff, y: 4 },
      { x: q.x + nOff, y: q.y },
    ]);
    wire('in:PE', 'PE', [
      { x: q.x + nOff * 2, y: 4 },
      { x: q.x + nOff * 2, y: q.y },
    ]);
  }

  for (const d of panel.devices) {
    if (!onRail(d)) continue;
    const p = products.get(d.productId);
    if (hasN(p)) {
      const x = left(d) + d.width * MODULE_PX - TERM_MARGIN;
      wire(`N:${d.id}`, 'N', [
        { x, y: nBarY(d) },
        { x, y: outPt(d).y },
      ]);
    }
    const code = p?.category.code;
    if (d.groupId !== null && (code === 'mcb' || code === 'rcbo')) {
      const exit = top(d) + ROW_PITCH - 3;
      const x0 = left(d) + TERM_MARGIN;
      const ph = threePhase ? phasesOf(d) : [];
      const nOff = ph.length > 1 ? 14 : 6;
      pushL(`out:L:${d.id}`, d, (dx) => [outPt(d), { x: x0 + dx, y: exit }]);
      wire(`out:N:${d.id}`, 'N', [
        { x: x0 + nOff, y: nBarY(d) },
        { x: x0 + nOff, y: exit },
      ]);
      wire(`out:PE:${d.id}`, 'PE', [
        { x: x0 + nOff * 2, y: peBarY(d) },
        { x: x0 + nOff * 2, y: exit },
      ]);
    }
  }

  const width = Math.max(...rails.map((r) => r.capacity), 0) * MODULE_PX;
  const height = WIRE_GAP + rails.length * ROW_PITCH;
  return { wires, bars, width, height };
}

const path = (pts: Pt[]): string =>
  pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x} ${p.y}`).join(' ');

/** SVG fragment for the wires and busbars; contains only numbers and constants. */
export function wiresToSvg(ws: WireSet): string {
  const out: string[] = [];
  for (const b of ws.bars) {
    const fill = b.kind === 'N' ? WIRE_COLOR.N : WIRE_COLOR.PE;
    out.push(
      `<g data-bar="${b.kind}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="6" rx="2" fill="${fill}"/>`,
    );
    if (b.kind === 'PE') {
      out.push(
        `<line x1="${b.x}" y1="${b.y + 3}" x2="${b.x + b.w}" y2="${b.y + 3}" stroke="${PE_STRIPE}" stroke-width="3" stroke-dasharray="6 6"/>`,
      );
    }
    out.push(
      `<text x="${b.x + 3}" y="${b.y - 1}" font-size="8" fill="#334155">${b.kind}</text></g>`,
    );
  }
  for (const w of ws.wires) {
    const d = path(w.points);
    out.push(
      `<g data-wire="${w.kind}"${w.phase ? ` data-phase="${w.phase}"` : ''} data-wire-id="${w.id}">`,
      `<path d="${d}" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round" opacity="0.85"/>`,
      `<path d="${d}" fill="none" stroke="${w.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`,
    );
    if (w.kind === 'PE') {
      out.push(
        `<path d="${d}" fill="none" stroke="${PE_STRIPE}" stroke-width="2.5" stroke-dasharray="5 5" stroke-linecap="butt"/>`,
      );
    }
    out.push('</g>');
  }
  return out.join('');
}
