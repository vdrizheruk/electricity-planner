import type { BoardStore } from './store';
import type { PanelModel } from './types';

export type SavePositions = (
  panelId: number,
  positions: PanelModel['diagramPositions'],
) => Promise<void>;

/**
 * Persist `diagramPositions` of every panel (debounced). Keys are translated to the stable
 * `s<serverId>` form and entries of devices that no longer exist are dropped.
 */
export function createPositionsSaver(
  store: BoardStore,
  save: SavePositions,
  delayMs = 600,
): { stop(): void; flush(): Promise<void> } {
  const timers = new Map<number, ReturnType<typeof setTimeout>>();
  const last = new Map<number, PanelModel['diagramPositions']>();
  for (const p of Object.values(store.getState().panels)) last.set(p.id, p.diagramPositions);

  function persistent(panel: PanelModel): PanelModel['diagramPositions'] {
    const out: PanelModel['diagramPositions'] = {};
    const ids = new Map(panel.devices.map((d) => [d.id, d.serverId]));
    for (const [key, pos] of Object.entries(panel.diagramPositions)) {
      if (key === 'feeder' || key === 'bus') out[key] = pos;
      else {
        const serverId = ids.get(key);
        if (serverId !== undefined && serverId !== null) out[`s${serverId}`] = pos;
      }
    }
    return out;
  }

  async function run(panelId: number): Promise<void> {
    const panel = store.getState().panels[panelId];
    if (!panel) return;
    await save(panelId, persistent(panel));
  }

  const unsubscribe = store.subscribe((state) => {
    for (const p of Object.values(state.panels)) {
      if (last.get(p.id) === p.diagramPositions) continue;
      last.set(p.id, p.diagramPositions);
      const t = timers.get(p.id);
      if (t) clearTimeout(t);
      timers.set(
        p.id,
        setTimeout(() => {
          timers.delete(p.id);
          void run(p.id).catch(() => undefined);
        }, delayMs),
      );
    }
  });

  return {
    stop() {
      unsubscribe();
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    },
    async flush() {
      const ids = [...timers.keys()];
      for (const id of ids) clearTimeout(timers.get(id));
      timers.clear();
      await Promise.all(ids.map(run));
    },
  };
}
