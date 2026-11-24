import type { SimResult } from '../../../api/endpoints';
import type { Diagram } from './diagram';
import type { PanelModel } from './types';

export interface Energized {
  powered: boolean;
  /** grid | generator | inverter | pv; null while dark. */
  source: string | null;
  /** Why a group is dark (not_backed_up, overload …), empty otherwise. */
  reason: string;
}

/**
 * Which diagram nodes / devices carry voltage for a simulation result.
 * Group breakers follow their group; RCD, bus, input chain and feeder are live when anything
 * downstream is; devices without any group below follow the panel (backup bus / PV / grid).
 */
export function energize(
  panel: PanelModel,
  diagram: Diagram,
  sim: SimResult | null,
): Map<string, Energized> {
  const out = new Map<string, Energized>();
  if (!sim) return out;

  const groups = new Map(sim.groups.map((g) => [g.id, g]));
  const base: Energized =
    panel.kind === 'dc'
      ? { powered: sim.pv_w > 0, source: sim.pv_w > 0 ? 'pv' : null, reason: '' }
      : panel.kind === 'backup'
        ? {
            powered: sim.backup_source !== null,
            source: sim.backup_source,
            reason: sim.backup_source ? '' : 'no_source',
          }
        : {
            powered: sim.main_source !== null,
            source: sim.main_source,
            reason: sim.main_source ? '' : 'no_source',
          };

  const children = new Map<string, string[]>();
  for (const e of diagram.edges)
    children.set(e.source, [...(children.get(e.source) ?? []), e.target]);
  const byId = new Map(diagram.nodes.map((n) => [n.id, n]));

  const visiting = new Set<string>();
  const state = (id: string): Energized | null => {
    const cached = out.get(id);
    if (cached) return cached;
    if (visiting.has(id)) return null;
    visiting.add(id);
    const node = byId.get(id);
    let res: Energized | null = null;
    if (panel.kind !== 'dc' && node?.groupId != null && groups.has(node.groupId)) {
      const g = groups.get(node.groupId)!;
      res = { powered: g.powered, source: g.powered ? g.source : null, reason: g.reason };
    } else {
      const below = (children.get(id) ?? []).map(state).filter((s): s is Energized => s !== null);
      const live = below.find((s) => s.powered);
      if (live) res = { powered: true, source: live.source, reason: '' };
      else if (below.length > 0)
        res = { powered: false, source: null, reason: below[0]?.reason ?? '' };
      else res = base;
    }
    visiting.delete(id);
    out.set(id, res);
    return res;
  };
  for (const n of diagram.nodes) state(n.id);
  return out;
}

/** Device id → state (the board view has devices only; feeder and bus are skipped). */
export function deviceStates(
  panel: PanelModel,
  diagram: Diagram,
  sim: SimResult | null,
): Map<string, Energized> {
  const all = energize(panel, diagram, sim);
  const out = new Map<string, Energized>();
  for (const n of diagram.nodes) {
    const s = all.get(n.id);
    if (n.deviceId && s) out.set(n.deviceId, s);
  }
  return out;
}
