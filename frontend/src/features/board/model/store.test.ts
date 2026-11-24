import { beforeEach, describe, expect, it } from 'vitest';
import { createBoardStore, type BoardStore } from './store';
import { device, panel, product } from './testkit';
import type { Group } from './types';

const mcb1 = product({ id: 1, modules: '1.0' });
const mcb3 = product({ id: 3, modules: '3.0', poles: 3 });
const relay = product({
  id: 4,
  modules: '3.0',
  category: { id: 9, code: 'voltage_relay', name_ru: '', name_uk: '' },
});
const contactor = product({
  id: 9,
  modules: '0.0',
  din_mountable: false,
  width_mm: 55,
  height_mm: 85,
  category: { id: 8, code: 'contactor', name_ru: '', name_uk: '' },
});
const group = (id: number): Group => ({ id, name: `g${id}` }) as Group;

let store: BoardStore;
const state = () => store.getState();
const dev = () => state().panels[1]!.devices;

function setup(devices = [] as ReturnType<typeof device>[]) {
  store = createBoardStore();
  state().load({
    panels: [
      panel({
        rails: [
          { id: 1, rowIndex: 0, capacity: 12 },
          { id: 2, rowIndex: 1, capacity: 12 },
        ],
        devices,
      }),
      panel({ id: 2, name: 'Этаж', rails: [{ id: 10, rowIndex: 0, capacity: 6 }] }),
    ],
    products: [mcb1, mcb3, relay, contactor],
    groups: [group(1), group(2)],
  });
}

beforeEach(() => setup());

describe('addProduct', () => {
  it('adds on a rail with the product width and selects the new device', () => {
    const r = state().addProduct(mcb3, { kind: 'rail', panelId: 1, railId: 1, start: 2 });
    expect(r.ok).toBe(true);
    expect(dev()).toHaveLength(1);
    expect(dev()[0]).toMatchObject({ railId: 1, start: 2, width: 3, productId: 3 });
    expect(state().selection).toEqual([dev()[0]!.id]);
  });

  it('rejects collisions and overflow without changing anything', () => {
    state().addProduct(mcb3, { kind: 'rail', panelId: 1, railId: 1, start: 2 });
    const rev = state().revisions[1];
    expect(state().addProduct(mcb1, { kind: 'rail', panelId: 1, railId: 1, start: 3 })).toEqual({
      ok: false,
      reason: 'collision',
    });
    expect(state().addProduct(mcb3, { kind: 'rail', panelId: 1, railId: 1, start: 10 })).toEqual({
      ok: false,
      reason: 'out_of_bounds',
    });
    expect(state().addProduct(mcb1, { kind: 'rail', panelId: 1, railId: 99, start: 0 })).toEqual({
      ok: false,
      reason: 'unknown',
    });
    expect(dev()).toHaveLength(1);
    expect(state().revisions[1]).toBe(rev);
  });

  it('enforces DIN vs mounting-panel compatibility', () => {
    expect(
      state().addProduct(contactor, { kind: 'rail', panelId: 1, railId: 1, start: 0 }),
    ).toEqual({ ok: false, reason: 'incompatible' });
    expect(state().addProduct(mcb1, { kind: 'mount', panelId: 1, x: 0, y: 0 })).toEqual({
      ok: false,
      reason: 'incompatible',
    });
    const ok = state().addProduct(contactor, { kind: 'mount', panelId: 1, x: 12, y: 7 });
    expect(ok.ok).toBe(true);
    expect(dev()[0]).toMatchObject({ x: 10, y: 5, w: 55, h: 85, railId: null }); // snapped to 5 mm
    expect(state().addProduct(contactor, { kind: 'mount', panelId: 1, x: 20, y: 20 }).ok).toBe(
      false,
    );
  });

  it('binds a group only to bindable products', () => {
    expect(
      state().addProduct(relay, { kind: 'rail', panelId: 1, railId: 1, start: 0 }, { groupId: 1 }),
    ).toEqual({ ok: false, reason: 'incompatible' });
    const r = state().addProduct(
      mcb1,
      { kind: 'rail', panelId: 1, railId: 1, start: 0 },
      { groupId: 1 },
    );
    expect(r.ok).toBe(true);
    expect(dev()[0]!.groupId).toBe(1);
  });
});

describe('moveDevices', () => {
  beforeEach(() => {
    setup([
      device('a', { railId: 1, start: 0, width: 3, productId: 3 }),
      device('b', { railId: 1, start: 4, width: 1 }),
      device('c', { railId: 2, start: 0, width: 1 }),
    ]);
  });

  it('moves a single device and bumps the revision', () => {
    const rev = state().revisions[1]!;
    expect(state().moveDevices('b', { kind: 'rail', panelId: 1, railId: 1, start: 8 }).ok).toBe(
      true,
    );
    expect(dev().find((d) => d.id === 'b')!.start).toBe(8);
    expect(state().revisions[1]).toBe(rev + 1);
  });

  it('allows overlapping its own old position', () => {
    expect(state().moveDevices('a', { kind: 'rail', panelId: 1, railId: 1, start: 1 }).ok).toBe(
      true,
    );
    expect(dev().find((d) => d.id === 'a')!.start).toBe(1);
  });

  it('refuses a collision and leaves state untouched', () => {
    const before = dev();
    expect(state().moveDevices('b', { kind: 'rail', panelId: 1, railId: 1, start: 2 })).toEqual({
      ok: false,
      reason: 'collision',
    });
    expect(dev()).toBe(before);
  });

  it('moves between rails and between panels', () => {
    expect(state().moveDevices('b', { kind: 'rail', panelId: 1, railId: 2, start: 5 }).ok).toBe(
      true,
    );
    expect(dev().find((d) => d.id === 'b')!.railId).toBe(2);
    expect(state().moveDevices('c', { kind: 'rail', panelId: 2, railId: 10, start: 5 }).ok).toBe(
      true,
    );
    expect(dev().map((d) => d.id)).not.toContain('c');
    expect(state().panels[2]!.devices[0]).toMatchObject({ id: 'c', railId: 10, start: 5 });
    // the narrower rail of panel 2 rejects a 3-module device at the end
    expect(state().moveDevices('a', { kind: 'rail', panelId: 2, railId: 10, start: 4 })).toEqual({
      ok: false,
      reason: 'out_of_bounds',
    });
  });

  it('moves a multi-selection by the anchor delta, keeping relative layout', () => {
    state().selectMany(['a', 'b']);
    expect(state().moveDevices('a', { kind: 'rail', panelId: 1, railId: 1, start: 2 }).ok).toBe(
      true,
    );
    expect(dev().find((d) => d.id === 'a')!.start).toBe(2);
    expect(dev().find((d) => d.id === 'b')!.start).toBe(6);
  });

  it('multi-move is all or nothing', () => {
    state().selectMany(['a', 'b']);
    const before = dev();
    // delta +8 pushes b (start 4 -> 12) over the edge
    expect(state().moveDevices('a', { kind: 'rail', panelId: 1, railId: 1, start: 8 }).ok).toBe(
      false,
    );
    expect(dev()).toBe(before);
  });

  it('multi-move across rows keeps row offsets', () => {
    setup([device('a', { railId: 1, start: 0 }), device('b', { railId: 2, start: 0 })]);
    state().selectMany(['a', 'b']);
    // can't go down: b would land on a non-existing 3rd row
    expect(state().moveDevices('a', { kind: 'rail', panelId: 1, railId: 2, start: 0 }).ok).toBe(
      false,
    );
  });

  it('moves mounting-panel items on the 5 mm grid', () => {
    setup([
      device('m', { productId: 9, railId: null, start: null, width: 0, x: 0, y: 0, w: 55, h: 85 }),
    ]);
    expect(state().moveDevices('m', { kind: 'mount', panelId: 1, x: 101, y: 52 }).ok).toBe(true);
    expect(dev()[0]).toMatchObject({ x: 100, y: 50 });
    expect(state().moveDevices('m', { kind: 'mount', panelId: 1, x: 190, y: 0 }).ok).toBe(false);
  });

  it('dropping onto the same spot is a no-op without history', () => {
    const past = state().past.length;
    expect(state().moveDevices('b', { kind: 'rail', panelId: 1, railId: 1, start: 4 }).ok).toBe(
      true,
    );
    expect(state().past.length).toBe(past);
  });
});

describe('remove / undo / redo', () => {
  beforeEach(() => {
    setup([device('a', { start: 0 }), device('b', { start: 1 })]);
  });

  it('removes devices and clears them from the selection', () => {
    state().selectMany(['a', 'b']);
    expect(state().removeDevices(['a']).ok).toBe(true);
    expect(dev().map((d) => d.id)).toEqual(['b']);
    expect(state().selection).toEqual(['b']);
    expect(state().removeDevices(['zzz'])).toEqual({ ok: false, reason: 'empty' });
  });

  it('undo and redo restore device lists', () => {
    state().removeDevices(['a']);
    state().addProduct(mcb1, { kind: 'rail', panelId: 1, railId: 1, start: 5 });
    expect(dev()).toHaveLength(2);
    expect(state().undo()).toBe(true);
    expect(dev().map((d) => d.id)).toEqual(['b']);
    expect(state().undo()).toBe(true);
    expect(dev().map((d) => d.id)).toEqual(['a', 'b']);
    expect(state().undo()).toBe(false);
    expect(state().redo()).toBe(true);
    expect(dev().map((d) => d.id)).toEqual(['b']);
    expect(state().redo()).toBe(true);
    expect(dev()).toHaveLength(2);
    expect(state().redo()).toBe(false);
  });

  it('a new action clears the redo stack; undo bumps revisions so autosave persists it', () => {
    state().removeDevices(['a']);
    const rev = state().revisions[1]!;
    state().undo();
    expect(state().revisions[1]).toBe(rev + 1);
    expect(state().future).toHaveLength(1);
    state().removeDevices(['b']);
    expect(state().future).toHaveLength(0);
  });

  it('undo across panels restores both lists', () => {
    state().moveDevices('a', { kind: 'rail', panelId: 2, railId: 10, start: 0 });
    expect(state().panels[2]!.devices).toHaveLength(1);
    state().undo();
    expect(state().panels[2]!.devices).toHaveLength(0);
    expect(dev().map((d) => d.id)).toEqual(['a', 'b']);
  });

  it('keeps at most 100 history entries', () => {
    for (let i = 0; i < 130; i++) state().setLabel('a', `l${i}`);
    expect(state().past).toHaveLength(100);
  });

  it('drops vanished ids from the selection on undo', () => {
    state().addProduct(mcb1, { kind: 'rail', panelId: 1, railId: 1, start: 5 });
    const added = state().selection[0]!;
    state().undo();
    expect(state().selection).not.toContain(added);
  });
});

describe('copy / paste', () => {
  beforeEach(() => {
    setup([
      device('a', { start: 0, width: 2, groupId: 5, label: 'x', serverId: 77 }),
      device('b', { start: 2, width: 1 }),
    ]);
  });

  it('pastes copies into the first free spots without group links or server ids', () => {
    state().selectMany(['a', 'b']);
    expect(state().copy()).toEqual({ ok: true, value: 2 });
    const r = state().paste(1);
    expect(r.ok).toBe(true);
    expect(dev()).toHaveLength(4);
    const copies = dev().slice(2);
    expect(copies.map((d) => d.start)).toEqual([3, 5]);
    expect(copies.every((d) => d.groupId === null && d.serverId === null)).toBe(true);
    expect(copies[0]!.label).toBe('x');
    expect(state().selection).toEqual(copies.map((d) => d.id));
    expect(new Set(dev().map((d) => d.id)).size).toBe(4);
  });

  it('pastes into another panel', () => {
    state().selectMany(['b']);
    state().copy();
    expect(state().paste(2).ok).toBe(true);
    expect(state().panels[2]!.devices[0]).toMatchObject({ railId: 10, start: 0 });
  });

  it('is all or nothing when there is no room', () => {
    state().selectMany(['a']);
    state().copy();
    const full = [device('f1', { railId: 10, start: 0, width: 5 })];
    state().replacePanelDevices(2, { ...state().panels[2]! }, full);
    const before = state().panels[2]!.devices;
    expect(state().paste(2)).toEqual({ ok: false, reason: 'no_space' });
    expect(state().panels[2]!.devices).toBe(before);
  });

  it('copy needs a selection, paste needs a clipboard', () => {
    state().clearSelection();
    expect(state().copy()).toEqual({ ok: false, reason: 'empty' });
    expect(state().paste(1)).toEqual({ ok: false, reason: 'empty' });
  });

  it('pastes mounting-panel items at a free spot', () => {
    setup([
      device('m', { productId: 9, railId: null, start: null, width: 0, x: 0, y: 0, w: 55, h: 85 }),
    ]);
    state().selectMany(['m']);
    state().copy();
    expect(state().paste(1).ok).toBe(true);
    expect(dev()[1]).toMatchObject({ x: 55, y: 0 });
  });
});

describe('groups, labels, selection, saving', () => {
  beforeEach(() =>
    setup([device('a', { start: 0, productId: 1 }), device('r', { start: 1, productId: 4 })]),
  );

  it('binds / unbinds groups with the compatibility rule', () => {
    expect(state().setGroup('a', 2).ok).toBe(true);
    expect(dev()[0]!.groupId).toBe(2);
    expect(state().setGroup('a', null).ok).toBe(true);
    expect(state().setGroup('r', 2)).toEqual({ ok: false, reason: 'incompatible' });
    expect(state().setGroup('nope', 2)).toEqual({ ok: false, reason: 'unknown' });
  });

  it('toggle selection', () => {
    state().select('a');
    state().select('r', 'toggle');
    expect(state().selection).toEqual(['a', 'r']);
    state().select('a', 'toggle');
    expect(state().selection).toEqual(['r']);
    state().select('a');
    expect(state().selection).toEqual(['a']);
    state().clearSelection();
    expect(state().selection).toEqual([]);
  });

  it('markSaved stores server ids without touching history or revisions', () => {
    const rev = state().revisions[1];
    const past = state().past.length;
    state().markSaved(1, [{ id: 'a', serverId: 11 }]);
    expect(dev()[0]!.serverId).toBe(11);
    expect(state().revisions[1]).toBe(rev);
    expect(state().past.length).toBe(past);
  });

  it('markSaved also patches history so undo keeps server ids', () => {
    state().removeDevices(['a']);
    state().markSaved(1, [{ id: 'a', serverId: 11 }]);
    state().undo();
    expect(dev().find((d) => d.id === 'a')!.serverId).toBe(11);
  });

  it('view and save status', () => {
    state().setView({ zoom: 1.5 });
    expect(state().view).toEqual({ zoom: 1.5, x: 0, y: 0 });
    state().setSave('error', 'boom');
    expect(state().save).toEqual({ state: 'error', error: 'boom' });
    state().setSave('saved');
    expect(state().save).toEqual({ state: 'saved' });
  });
});
