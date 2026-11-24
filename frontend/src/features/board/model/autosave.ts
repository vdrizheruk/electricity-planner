import type { BoardStore } from './store';
import type { Device } from './types';

export type SaveFn = (
  panelId: number,
  devices: Device[],
) => Promise<{ id: string; serverId: number }[]>;

export interface Autosaver {
  /** Save everything that is pending now and wait for it. */
  flush(): Promise<void>;
  stop(): void;
}

/**
 * Debounced autosave: watches per-panel revisions in the store and PUTs the full panel
 * state after `delayMs` of quiet. Saves of one panel never overlap.
 */
export function createAutosaver(store: BoardStore, save: SaveFn, delayMs = 700): Autosaver {
  const saved: Record<number, number> = {};
  const timers = new Map<number, ReturnType<typeof setTimeout>>();
  const running = new Map<number, Promise<void>>();

  for (const [id, rev] of Object.entries(store.getState().revisions)) saved[Number(id)] = rev;

  async function run(panelId: number): Promise<void> {
    const prev = running.get(panelId);
    if (prev) await prev;
    const state = store.getState();
    const panel = state.panels[panelId];
    const rev = state.revisions[panelId] ?? 0;
    if (!panel || (saved[panelId] ?? 0) === rev) return;
    store.getState().setSave('saving');
    const task = (async () => {
      try {
        const result = await save(panelId, panel.devices);
        store.getState().markSaved(panelId, result);
        saved[panelId] = rev;
        const pending = Object.keys(store.getState().revisions).some(
          (k) => (store.getState().revisions[Number(k)] ?? 0) !== (saved[Number(k)] ?? 0),
        );
        if (!pending) store.getState().setSave('saved');
      } catch (e) {
        store.getState().setSave('error', e instanceof Error ? e.message : String(e));
      }
    })();
    running.set(panelId, task);
    await task;
    running.delete(panelId);
  }

  function schedule(panelId: number): void {
    const t = timers.get(panelId);
    if (t) clearTimeout(t);
    timers.set(
      panelId,
      setTimeout(() => {
        timers.delete(panelId);
        void run(panelId);
      }, delayMs),
    );
  }

  const unsubscribe = store.subscribe((state, prev) => {
    for (const [idStr, rev] of Object.entries(state.revisions)) {
      const id = Number(idStr);
      if (rev !== (prev.revisions[id] ?? 0) && rev !== (saved[id] ?? 0)) schedule(id);
    }
  });

  return {
    async flush() {
      const ids = [...timers.keys()];
      for (const id of ids) {
        clearTimeout(timers.get(id));
        timers.delete(id);
      }
      const all = new Set([...ids, ...Object.keys(store.getState().revisions).map(Number)]);
      await Promise.all([...all].map((id) => run(id)));
    },
    stop() {
      unsubscribe();
      for (const t of timers.values()) clearTimeout(t);
      timers.clear();
    },
  };
}
