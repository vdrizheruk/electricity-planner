import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createAutosaver, type Autosaver, type SaveFn } from './autosave';
import { createBoardStore, type BoardStore } from './store';
import { panel, product } from './testkit';

const mcb = product({ id: 1 });
let store: BoardStore;
let saver: Autosaver;
let save: ReturnType<typeof vi.fn<SaveFn>>;

function add(start: number) {
  store.getState().addProduct(mcb, { kind: 'rail', panelId: 1, railId: 1, start });
}

beforeEach(() => {
  vi.useFakeTimers();
  store = createBoardStore();
  store
    .getState()
    .load({ panels: [panel(), panel({ id: 2, name: 'B' })], products: [mcb], groups: [] });
  save = vi.fn<SaveFn>(async (_id, devices) =>
    devices.map((d, i) => ({ id: d.id, serverId: 100 + i })),
  );
  saver = createAutosaver(store, save, 500);
});
afterEach(() => {
  saver.stop();
  vi.useRealTimers();
});

describe('autosave', () => {
  it('debounces rapid edits into one save of the final state', async () => {
    add(0);
    await vi.advanceTimersByTimeAsync(300);
    add(1);
    await vi.advanceTimersByTimeAsync(300);
    expect(save).not.toHaveBeenCalled();
    add(2);
    await vi.advanceTimersByTimeAsync(499);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0]![0]).toBe(1);
    expect(save.mock.calls[0]![1]).toHaveLength(3);
    expect(store.getState().save.state).toBe('saved');
    expect(store.getState().panels[1]!.devices.map((d) => d.serverId)).toEqual([100, 101, 102]);
  });

  it('does nothing when nothing changed, and does not re-save unchanged panels', async () => {
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).not.toHaveBeenCalled();
    add(0);
    await vi.advanceTimersByTimeAsync(600);
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('saves each panel separately', async () => {
    add(0);
    store.getState().addProduct(mcb, { kind: 'rail', panelId: 2, railId: 1, start: 0 });
    await vi.advanceTimersByTimeAsync(600);
    expect(save.mock.calls.map((c) => c[0]).sort()).toEqual([1, 2]);
  });

  it('reports errors and retries on the next change', async () => {
    save.mockRejectedValueOnce(new Error('layout: collision'));
    add(0);
    await vi.advanceTimersByTimeAsync(600);
    expect(store.getState().save).toEqual({ state: 'error', error: 'layout: collision' });
    add(1);
    await vi.advanceTimersByTimeAsync(600);
    expect(save).toHaveBeenCalledTimes(2);
    expect(store.getState().save.state).toBe('saved');
  });

  it('undo is saved too', async () => {
    add(0);
    await vi.advanceTimersByTimeAsync(600);
    store.getState().undo();
    await vi.advanceTimersByTimeAsync(600);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1]![1]).toHaveLength(0);
  });

  it('flush saves pending changes immediately', async () => {
    add(0);
    await saver.flush();
    expect(save).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(save).toHaveBeenCalledTimes(1);
  });

  it('does not overlap saves of one panel and saves the latest state after', async () => {
    let release: () => void = () => {};
    save.mockImplementationOnce(
      (_id, devices) =>
        new Promise((resolve) => {
          release = () => resolve(devices.map((d, i) => ({ id: d.id, serverId: i + 1 })));
        }),
    );
    add(0);
    await vi.advanceTimersByTimeAsync(600); // first save started, pending
    add(1);
    await vi.advanceTimersByTimeAsync(600); // second save queued behind the first
    expect(save).toHaveBeenCalledTimes(1);
    release();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1]![1]).toHaveLength(2);
  });
});
