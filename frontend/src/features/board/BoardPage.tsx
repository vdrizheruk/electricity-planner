import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragMoveEvent,
  type DragStartEvent,
} from '@dnd-kit/core';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { bomApi, groups as groupsApi, panels as panelsApi } from '../../api/endpoints';
import { saveBlob } from '../../shared/saveBlob';
import { toCents, type BomExtra } from './model/bom';
import { loadBoard, reloadPanel, savePanel } from './api';
import { DiagramView } from './components/DiagramView';
import { AutolayoutDialog, VersionsDialog } from './components/Dialogs';
import { PanelView, type Hover } from './components/PanelView';
import { Palette } from './components/Palette';
import { BomView, IssuesView, Properties } from './components/Sidebar';
import { UnplacedList } from './components/UnplacedList';
import { probe, type DragData } from './dragTarget';
import { createAutosaver, type Autosaver } from './model/autosave';
import { createPositionsSaver } from './model/positionsSaver';
import { buildDiagram } from './model/diagram';
import { diagramToSvg } from './model/diagramSvg';
import { boardToSvg } from './model/exportSvg';
import { PHASE_COLOR } from './model/wires';
import { labelItems, labelsToSvg } from './model/labels';
import {
  findFreeSpot,
  isPlaceableOnRail,
  productModules,
  requiredWidth,
  validatePanel,
} from './model/geometry';
import { breakerFor } from './model/match';
import { createBoardStore, type BoardStore } from './model/store';
import type { Group, Product } from './model/types';
import { useBoard, useIsNarrow } from './useStore';

function Trash({ label }: { label: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: 'trash' });
  return (
    <div
      ref={setNodeRef}
      data-trash=""
      data-testid="trash"
      className={`rounded border-2 border-dashed px-3 py-1 text-sm ${isOver ? 'border-red-600 bg-red-50' : 'border-slate-400'}`}
    >
      🗑 {label}
    </div>
  );
}

export function BoardPage() {
  const { t } = useTranslation();
  const projectId = Number(useParams().id);
  const store = useRef<BoardStore>(createBoardStore()).current;
  const saver = useRef<Autosaver | null>(null);
  const positionsSaver = useRef<{ stop(): void; flush(): Promise<void> } | null>(null);
  const narrow = useIsNarrow();
  const readOnly = narrow;

  const [ready, setReady] = useState(false);
  const [tier, setTier] = useState('mid');
  const [activeId, setActiveId] = useState<number | null>(null);
  const [hover, setHover] = useState<Hover>(null);
  const [drag, setDrag] = useState<DragData | null>(null);
  const [toast, setToast] = useState('');
  const [threePhase, setThreePhase] = useState(false);
  const [showWires, setShowWires] = useState(true);
  const [mode, setMode] = useState<'board' | 'diagram'>('board');
  const [dialog, setDialog] = useState<'autolayout' | 'versions' | null>(null);
  const [marquee, setMarquee] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(
    null,
  );
  const grab = useRef({ x: 0, y: 0 });
  const canvas = useRef<HTMLDivElement>(null);

  const panels = useBoard(store, (s) => s.panels);
  const order = useBoard(store, (s) => s.order);
  const products = useBoard(store, (s) => s.products);
  const groups = useBoard(store, (s) => s.groups);
  const selection = useBoard(store, (s) => s.selection);
  const view = useBoard(store, (s) => s.view);
  const save = useBoard(store, (s) => s.save);
  const canUndo = useBoard(store, (s) => s.past.length > 0);
  const canRedo = useBoard(store, (s) => s.future.length > 0);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));

  const [extra, setExtra] = useState<BomExtra>({});

  const load = useCallback(async () => {
    const b = await loadBoard(projectId);
    // Solar and backup equipment are not drawn in the editor: take their totals from the server.
    void bomApi
      .get(projectId)
      .then((bom) =>
        setExtra({
          solarCents: toCents(bom.sections.find((x) => x.key === 'solar')?.total ?? '0'),
          backupCents: toCents(bom.sections.find((x) => x.key === 'backup')?.total ?? '0'),
        }),
      )
      .catch(() => setExtra({}));
    store.getState().load({ panels: b.panels, products: b.products, groups: b.groups });
    setTier(b.project.price_tier ?? 'mid');
    setThreePhase(b.project.grid === '3ph');
    setActiveId((cur) => cur ?? b.panels[0]?.id ?? null);
    saver.current?.stop();
    saver.current = createAutosaver(store, savePanel);
    positionsSaver.current?.stop();
    positionsSaver.current = createPositionsSaver(store, async (id, positions) => {
      await panelsApi.update(id, { diagram_positions: positions });
    });
    setReady(true);
  }, [projectId, store]);

  useEffect(() => {
    void load();
    return () => {
      saver.current?.stop();
      void positionsSaver.current?.flush().then(() => positionsSaver.current?.stop());
    };
  }, [load]);

  useEffect(() => {
    const beforeUnload = (e: BeforeUnloadEvent) => {
      const s = store.getState().save.state;
      if (s === 'saving' || s === 'error') e.preventDefault();
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [store]);

  const flash = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(''), 2500);
  }, []);
  const fail = useCallback(
    (reason: string) => flash(t(`board.errors.${reason}`, { defaultValue: reason })),
    [flash, t],
  );

  const panelList = useMemo(
    () => order.map((id) => panels[id]).filter((p) => p !== undefined),
    [order, panels],
  );
  const productList = useMemo(() => [...products.values()], [products]);
  const enclosures = useMemo(
    () => productList.filter((p) => p.category.code === 'enclosure'),
    [productList],
  );
  const palette = useMemo(
    () => productList.filter((p) => !['enclosure', 'mount_panel'].includes(p.category.code)),
    [productList],
  );
  const issuesByPanel = useMemo(
    () => panelList.map((p) => validatePanel(p, products)),
    [panelList, products],
  );
  const placedGroups = useMemo(
    () =>
      new Set(panelList.flatMap((p) => p.devices.map((d) => d.groupId)).filter((g) => g !== null)),
    [panelList],
  );
  const unplaced = useMemo(
    () => groups.filter((g) => g.breaker_a !== null && !placedGroups.has(g.id)),
    [groups, placedGroups],
  );
  const active = (activeId !== null ? panels[activeId] : undefined) ?? panelList[0];

  /** Click-to-add: put a product at the first free spot of the active panel. */
  function addToActive(product: Product, groupId: number | null = null): void {
    if (!active) return;
    const s = store.getState();
    const panel = s.panels[active.id];
    if (!panel) return;
    if (isPlaceableOnRail(product)) {
      const spot = findFreeSpot(panel, requiredWidth(productModules(product)));
      if (!spot) return fail('no_space');
      const r = s.addProduct(product, { kind: 'rail', panelId: panel.id, ...spot }, { groupId });
      if (!r.ok) fail(r.reason);
    } else {
      const w = product.width_mm ?? 50;
      const h = product.height_mm ?? 80;
      const aw = panel.area.width ?? 0;
      const ah = panel.area.height ?? 0;
      for (let y = 0; y + h <= ah; y += 5) {
        for (let x = 0; x + w <= aw; x += 5) {
          const r = s.addProduct(product, { kind: 'mount', panelId: panel.id, x, y }, { groupId });
          if (r.ok) return;
        }
      }
      fail('no_space');
    }
  }

  function addGroup(g: Group): void {
    const p = breakerFor(g, productList, tier);
    if (!p) return fail('incompatible');
    addToActive(p, g.id);
  }

  // ---- drag & drop -------------------------------------------------------
  const pointerOf = (e: { activatorEvent: Event; delta: { x: number; y: number } }) => {
    const ev = e.activatorEvent as PointerEvent;
    return { x: ev.clientX + e.delta.x, y: ev.clientY + e.delta.y };
  };

  function onDragStart(e: DragStartEvent) {
    const d = e.active.data.current as {
      type: string;
      product?: Product;
      group?: Group;
      deviceId?: string;
      panelId?: number;
    };
    const ev = e.activatorEvent as PointerEvent;
    const r = e.active.rect.current.initial;
    grab.current = r ? { x: ev.clientX - r.left, y: ev.clientY - r.top } : { x: 0, y: 0 };
    if (d.type === 'palette' && d.product) setDrag({ type: 'palette', product: d.product });
    else if (d.type === 'group' && d.group)
      setDrag({
        type: 'group',
        groupId: d.group.id,
        product: breakerFor(d.group, productList, tier),
      });
    else if (d.type === 'device' && d.deviceId) {
      setDrag({ type: 'device', deviceId: d.deviceId, panelId: d.panelId as number });
      const s = store.getState();
      if (!s.selection.includes(d.deviceId)) s.select(d.deviceId);
    }
  }

  function onDragMove(e: DragMoveEvent) {
    if (!drag) return;
    const p = pointerOf(e);
    setHover(
      probe(drag, p.x, p.y, { state: store.getState(), zoom: view.zoom, grabPx: grab.current })
        .hover,
    );
  }

  function onDragEnd(e: DragEndEvent) {
    const data = drag;
    setDrag(null);
    setHover(null);
    if (!data) return;
    const p = pointerOf(e);
    const res = probe(data, p.x, p.y, {
      state: store.getState(),
      zoom: view.zoom,
      grabPx: grab.current,
    });
    const s = store.getState();
    if (res.trash && data.type === 'device') {
      const ids = s.selection.includes(data.deviceId) ? s.selection : [data.deviceId];
      s.removeDevices(ids);
      return;
    }
    if (!res.target) return;
    if (data.type === 'device') {
      const r = s.moveDevices(data.deviceId, res.target);
      if (!r.ok) fail(r.reason);
    } else if (data.type === 'palette') {
      const r = s.addProduct(data.product, res.target);
      if (!r.ok) fail(r.reason);
    } else if (data.product) {
      const r = s.addProduct(data.product, res.target, { groupId: data.groupId });
      if (!r.ok) fail(r.reason);
    }
  }

  // ---- keyboard ----------------------------------------------------------
  useEffect(() => {
    if (readOnly) return;
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      const mod = e.ctrlKey || e.metaKey;
      const s = store.getState();
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) s.redo();
        else s.undo();
      } else if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        s.redo();
      } else if (mod && e.key.toLowerCase() === 'c') {
        s.copy();
      } else if (mod && e.key.toLowerCase() === 'v') {
        if (active) {
          const r = s.paste(active.id);
          if (!r.ok) fail(r.reason);
        }
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        s.removeDevices(s.selection);
      } else if (e.key === 'Escape') {
        s.clearSelection();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [store, readOnly, active, fail]);

  // ---- zoom / pan / marquee ----------------------------------------------
  function onWheel(e: React.WheelEvent) {
    if (e.ctrlKey || e.metaKey) {
      const z = Math.min(3, Math.max(0.25, view.zoom * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
      store.getState().setView({ zoom: z });
    } else {
      store.getState().setView({ x: view.x - e.deltaX, y: view.y - e.deltaY });
    }
  }

  const panning = useRef<{ x: number; y: number } | null>(null);
  function onCanvasDown(e: React.PointerEvent) {
    if (e.target !== e.currentTarget && !(e.target as HTMLElement).dataset.surface) return;
    if (e.button === 1 || e.altKey) {
      panning.current = { x: e.clientX, y: e.clientY };
    } else if (e.button === 0 && !readOnly) {
      setMarquee({ x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY });
      if (!(e.shiftKey || e.ctrlKey)) store.getState().clearSelection();
    }
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }
  function onCanvasMove(e: React.PointerEvent) {
    if (panning.current) {
      const dx = e.clientX - panning.current.x;
      const dy = e.clientY - panning.current.y;
      panning.current = { x: e.clientX, y: e.clientY };
      store.getState().setView({ x: view.x + dx, y: view.y + dy });
    } else if (marquee) {
      setMarquee({ ...marquee, x1: e.clientX, y1: e.clientY });
    }
  }
  function onCanvasUp() {
    panning.current = null;
    if (!marquee) return;
    const r = {
      l: Math.min(marquee.x0, marquee.x1),
      r: Math.max(marquee.x0, marquee.x1),
      t: Math.min(marquee.y0, marquee.y1),
      b: Math.max(marquee.y0, marquee.y1),
    };
    if (r.r - r.l > 3 || r.b - r.t > 3) {
      const ids = [...document.querySelectorAll<HTMLElement>('[data-device-id]')]
        .filter((el) => {
          const b = el.getBoundingClientRect();
          return b.left < r.r && b.right > r.l && b.top < r.b && b.bottom > r.t;
        })
        .map((el) => el.dataset.deviceId as string);
      const s = store.getState();
      s.selectMany([...new Set([...(marquee ? s.selection : []), ...ids])]);
    }
    setMarquee(null);
  }

  // ---- actions -----------------------------------------------------------
  const refreshPanel = useCallback(
    async (panelId: number) => {
      await saver.current?.flush();
      const model = await reloadPanel(panelId, projectId);
      const { devices, ...meta } = model;
      store.getState().replacePanelDevices(panelId, meta, devices);
    },
    [projectId, store],
  );

  async function addPanel() {
    const name = prompt(t('board.panelName'), `${t('board.createPanel')} ${panelList.length + 1}`);
    if (!name) return;
    await saver.current?.flush();
    const p = await panelsApi.create(projectId, { name, kind: 'floor' });
    await load();
    setActiveId(p.id);
  }

  async function setEnclosure(panelId: number, enclosure: number | null) {
    await saver.current?.flush();
    await panelsApi.update(panelId, { enclosure });
    await refreshPanel(panelId);
  }

  const download = saveBlob;
  async function exportPdf() {
    await saver.current?.flush();
    const images = panelList.flatMap((p) => [
      {
        panel_id: p.id,
        kind: 'board' as const,
        svg: boardToSvg(p, products, groups, threePhase).svg,
      },
      {
        panel_id: p.id,
        kind: 'diagram' as const,
        svg: diagramToSvg(buildDiagram(p, products, groups), p.name).svg,
      },
    ]);
    try {
      download(`specification-${projectId}.pdf`, await bomApi.pdf(projectId, images));
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e));
    }
  }
  function currentSvg() {
    if (!active) return null;
    return mode === 'diagram'
      ? diagramToSvg(buildDiagram(active, products, groups), active.name)
      : boardToSvg(active, products, groups, threePhase);
  }
  function exportLabels() {
    if (!active) return;
    const { svg } = labelsToSvg(labelItems(active, products, groups), active.name);
    download(`${active.name}-labels.svg`, new Blob([svg], { type: 'image/svg+xml' }));
  }
  function exportSvg() {
    const r = currentSvg();
    if (!active || !r) return;
    download(
      `${active.name}${mode === 'diagram' ? '-scheme' : ''}.svg`,
      new Blob([r.svg], { type: 'image/svg+xml' }),
    );
  }
  function exportPng() {
    const r = currentSvg();
    if (!active || !r) return;
    const { svg, width, height } = r;
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = width * 2;
      c.height = height * 2;
      const ctx = c.getContext('2d');
      if (!ctx) return;
      ctx.scale(2, 2);
      ctx.drawImage(img, 0, 0);
      c.toBlob((b) => b && download(`${active.name}.png`, b));
    };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

  if (!ready) return <div className="p-4">{t('app.loading')}</div>;

  const saveLabel = {
    idle: t('board.idle'),
    saving: t('board.saving'),
    saved: t('board.saved'),
    error: t('board.saveError'),
  }[save.state];
  const overlayProduct =
    drag &&
    (drag.type === 'device'
      ? products.get(
          Object.values(panels)
            .flatMap((p) => p.devices)
            .find((d) => d.id === drag.deviceId)?.productId ?? -1,
        )
      : drag.product);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={onDragStart}
      onDragMove={onDragMove}
      onDragEnd={onDragEnd}
      onDragCancel={() => {
        setDrag(null);
        setHover(null);
      }}
    >
      <div className="flex h-full flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b bg-white px-3 py-1.5">
          <div role="tablist" className="flex overflow-hidden rounded border">
            {(['board', 'diagram'] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                data-testid={`tab-${m}`}
                className={`px-3 py-1 text-sm ${mode === m ? 'bg-blue-600 text-white' : 'bg-white'}`}
                onClick={() => setMode(m)}
              >
                {t(`board.view.${m}`)}
              </button>
            ))}
          </div>
          <button
            className="btn"
            disabled={readOnly || !canUndo}
            onClick={() => store.getState().undo()}
          >
            ↶ {t('board.undo')}
          </button>
          <button
            className="btn"
            disabled={readOnly || !canRedo}
            onClick={() => store.getState().redo()}
          >
            ↷ {t('board.redo')}
          </button>
          <button
            className="btn"
            disabled={readOnly || selection.length === 0}
            onClick={() => store.getState().copy()}
          >
            {t('board.copy')}
          </button>
          <button
            className="btn"
            disabled={readOnly || !active}
            onClick={() => active && store.getState().paste(active.id)}
          >
            {t('board.paste')}
          </button>
          <button
            className="btn"
            disabled={readOnly || selection.length === 0}
            onClick={() => store.getState().removeDevices(selection)}
          >
            {t('board.delete')}
          </button>
          <span className="mx-1 h-5 border-l" />
          <button
            className="btn"
            aria-label={t('board.zoomOut')}
            onClick={() => store.getState().setView({ zoom: Math.max(0.25, view.zoom / 1.2) })}
          >
            −
          </button>
          <span className="w-12 text-center text-sm" data-testid="zoom">
            {Math.round(view.zoom * 100)}%
          </span>
          <button
            className="btn"
            aria-label={t('board.zoomIn')}
            onClick={() => store.getState().setView({ zoom: Math.min(3, view.zoom * 1.2) })}
          >
            +
          </button>
          <button className="btn" onClick={() => store.getState().setView({ zoom: 1, x: 0, y: 0 })}>
            {t('board.zoomReset')}
          </button>
          <span className="mx-1 h-5 border-l" />
          <button
            className="btn"
            disabled={readOnly || !active}
            onClick={() => setDialog('autolayout')}
          >
            {t('board.autolayout')}
          </button>
          <button className="btn" disabled={!active} onClick={() => setDialog('versions')}>
            {t('board.versions')}
          </button>
          <button className="btn" disabled={readOnly} onClick={() => void addPanel()}>
            ＋ {t('board.createPanel')}
          </button>
          <button className="btn" onClick={exportSvg}>
            {t('board.exportSvg')}
          </button>
          <button className="btn" onClick={exportPng}>
            {t('board.exportPng')}
          </button>
          <button className="btn" data-testid="export-pdf-board" onClick={() => void exportPdf()}>
            {t('board.exportPdf')}
          </button>
          <button className="btn" disabled={!active} onClick={exportLabels}>
            {t('board.exportLabels')}
          </button>
          <label className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              data-testid="toggle-wires"
              checked={showWires}
              onChange={(e) => setShowWires(e.target.checked)}
            />
            {t('board.wires')}
            <span className="ml-1 inline-flex items-center gap-1 text-[11px]">
              {threePhase ? (
                <>
                  <i className="inline-block h-1 w-4" style={{ background: PHASE_COLOR.L1 }} /> L1
                  <i className="inline-block h-1 w-4" style={{ background: PHASE_COLOR.L2 }} /> L2
                  <i className="inline-block h-1 w-4" style={{ background: PHASE_COLOR.L3 }} /> L3
                </>
              ) : (
                <>
                  <i className="inline-block h-1 w-4 bg-red-600" /> L
                </>
              )}
              <i className="inline-block h-1 w-4 bg-blue-600" /> N
              <i className="inline-block h-1 w-4 bg-yellow-400" /> PE
            </span>
          </label>
          {mode === 'diagram' && (
            <button
              className="btn"
              data-testid="reset-layout"
              disabled={!active}
              onClick={() => active && store.getState().resetNodePositions(active.id)}
            >
              {t('board.resetLayout')}
            </button>
          )}
          {!readOnly && <Trash label={t('board.trash')} />}
          <span
            data-testid="save-state"
            data-state={save.state}
            className={`ml-auto text-sm ${save.state === 'error' ? 'text-red-600' : 'text-slate-500'}`}
            title={save.error}
          >
            {saveLabel}
          </span>
        </div>
        {readOnly && <div className="bg-amber-100 px-3 py-1 text-sm">{t('board.readonly')}</div>}
        <div className="flex min-h-0 flex-1">
          {!readOnly && (
            <aside className="flex w-72 shrink-0 flex-col gap-3 border-r bg-white p-2">
              <UnplacedList groups={unplaced} onAdd={addGroup} readOnly={readOnly} />
              <Palette products={palette} onAdd={(p) => addToActive(p)} readOnly={readOnly} />
            </aside>
          )}
          {mode === 'diagram' && active ? (
            <div className="min-w-0 flex-1 bg-slate-50">
              <DiagramView store={store} panelId={active.id} />
            </div>
          ) : (
            <div
              ref={canvas}
              data-surface="1"
              data-testid="canvas"
              className="relative min-w-0 flex-1 overflow-hidden bg-slate-100"
              onWheel={onWheel}
              onPointerDown={onCanvasDown}
              onPointerMove={onCanvasMove}
              onPointerUp={onCanvasUp}
            >
              <div
                data-surface="1"
                style={{
                  transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
                  transformOrigin: '0 0',
                }}
                className="inline-block p-4"
              >
                {panelList.map((p) => (
                  <div key={p.id}>
                    <PanelView
                      panel={p}
                      products={products}
                      groups={groups}
                      selection={selection}
                      issues={issuesByPanel[panelList.indexOf(p)] ?? []}
                      hover={hover}
                      active={active?.id === p.id}
                      readOnly={readOnly}
                      showWires={showWires}
                      threePhase={threePhase}
                      enclosures={enclosures}
                      onActivate={() => setActiveId(p.id)}
                      onDeviceClick={(id, add) =>
                        store.getState().select(id, add ? 'toggle' : 'replace')
                      }
                      onEnclosure={(id) => void setEnclosure(p.id, id)}
                    />
                  </div>
                ))}
              </div>
              {marquee && (
                <div
                  className="pointer-events-none fixed border border-blue-600 bg-blue-300/20"
                  style={{
                    left: Math.min(marquee.x0, marquee.x1),
                    top: Math.min(marquee.y0, marquee.y1),
                    width: Math.abs(marquee.x1 - marquee.x0),
                    height: Math.abs(marquee.y1 - marquee.y0),
                  }}
                />
              )}
              {toast && (
                <div
                  data-testid="toast"
                  className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded bg-slate-800 px-3 py-1 text-sm text-white"
                >
                  {toast}
                </div>
              )}
            </div>
          )}
          <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto border-l bg-white p-2 lg:flex">
            {!readOnly && <Properties store={store} groups={groups} products={products} />}
            <IssuesView issues={issuesByPanel.flat()} />
            <BomView panels={panelList} products={products} extra={extra} />
          </aside>
        </div>
      </div>
      <DragOverlay dropAnimation={null}>
        {overlayProduct ? (
          <div className="rounded border border-slate-700 bg-white/90 px-2 py-1 text-xs shadow">
            {overlayProduct.brand.name} {overlayProduct.sku}
          </div>
        ) : null}
      </DragOverlay>
      {dialog === 'autolayout' && active && (
        <AutolayoutDialog
          panelId={active.id}
          onClose={() => setDialog(null)}
          onDone={async () => {
            await saver.current?.flush();
            await refreshPanel(active.id);
            const g = await groupsApi.list(projectId);
            store.getState().setGroups(g);
          }}
        />
      )}
      {dialog === 'versions' && active && (
        <VersionsDialog
          panelId={active.id}
          flush={async () => {
            await saver.current?.flush();
          }}
          onClose={() => setDialog(null)}
          onDone={() => refreshPanel(active.id)}
        />
      )}
    </DndContext>
  );
}
