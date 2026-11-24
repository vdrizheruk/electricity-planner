import { useDroppable } from '@dnd-kit/core';
import { useTranslation } from 'react-i18next';
import { freeModules, MM_PX, MODULE_PX, RAIL_HEIGHT_PX } from '../model/geometry';
import type { Device, Group, Issue, PanelModel, Product } from '../model/types';
import { buildWires, WIRE_GAP, wiresToSvg } from '../model/wires';
import { useMemo } from 'react';
import { DeviceView } from './DeviceView';

export type Hover =
  | { panelId: number; kind: 'rail'; railId: number; start: number; width: number; valid: boolean }
  | { panelId: number; kind: 'mount'; x: number; y: number; w: number; h: number; valid: boolean }
  | null;

interface Props {
  panel: PanelModel;
  products: Map<number, Product>;
  groups: Group[];
  selection: string[];
  issues: Issue[];
  hover: Hover;
  active: boolean;
  readOnly: boolean;
  showWires: boolean;
  threePhase: boolean;
  enclosures: Product[];
  onActivate: () => void;
  onDeviceClick: (id: string, additive: boolean) => void;
  onEnclosure: (id: number | null) => void;
}

function Ghost({
  left,
  top,
  width,
  height,
  valid,
}: {
  left: number;
  top: number;
  width: number;
  height: number;
  valid: boolean;
}) {
  return (
    <div
      data-testid="ghost"
      data-valid={valid}
      className={`pointer-events-none absolute rounded border-2 ${valid ? 'border-green-600 bg-green-300/50' : 'border-red-600 bg-red-300/50'}`}
      style={{ left, top, width, height }}
    />
  );
}

export function PanelView({
  panel,
  products,
  groups,
  selection,
  issues,
  hover,
  active,
  readOnly,
  showWires,
  threePhase,
  enclosures,
  onActivate,
  onDeviceClick,
  onEnclosure,
}: Props) {
  const { t } = useTranslation();
  const rails = [...panel.rails].sort((a, b) => a.rowIndex - b.rowIndex);
  const groupById = new Map(groups.map((g) => [g.id, g]));
  const bad = new Set(issues.flatMap((i) => [i.deviceId, ...(i.otherId ? [i.otherId] : [])]));
  const mine = hover && hover.panelId === panel.id ? hover : null;
  const mountW = (panel.area.width ?? 0) * MM_PX;
  const mountH = (panel.area.height ?? 0) * MM_PX;
  const wires = useMemo(
    () => buildWires(panel, products, groups, threePhase),
    [panel, products, groups, threePhase],
  );
  const { setNodeRef: mountRef } = useDroppable({ id: `mount-${panel.id}` });

  const render = (d: Device) => (
    <DeviceView
      key={d.id}
      device={d}
      panelId={panel.id}
      product={products.get(d.productId)}
      group={d.groupId !== null ? groupById.get(d.groupId) : undefined}
      selected={selection.includes(d.id)}
      invalid={bad.has(d.id)}
      readOnly={readOnly}
      onClick={onDeviceClick}
    />
  );

  return (
    <section
      data-testid="panel"
      data-panel-id={panel.id}
      onPointerDown={onActivate}
      className={`mb-6 inline-block rounded-lg border-2 bg-white p-3 ${active ? 'border-blue-500' : 'border-slate-300'}`}
    >
      <header className="mb-2 flex items-center gap-3 text-sm">
        <strong>{panel.name}</strong>
        <span className="text-slate-500">IP{panel.ip}</span>
        <span className="text-slate-500">
          {t('board.free')}: {freeModules(panel)}
        </span>
        {!readOnly && (
          <select
            aria-label={t('board.enclosure')}
            className="input"
            value={panel.enclosureId ?? ''}
            onChange={(e) => onEnclosure(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">—</option>
            {enclosures.map((p) => (
              <option key={p.id} value={p.id}>
                {p.brand.name} {p.sku}
              </option>
            ))}
          </select>
        )}
      </header>
      <div className="flex items-start gap-4">
        <div
          className="relative flex flex-col"
          style={{ gap: WIRE_GAP, paddingTop: WIRE_GAP, paddingBottom: WIRE_GAP }}
        >
          {rails.map((r) => (
            <RailRow key={r.id} panelId={panel.id} rail={r}>
              {panel.devices.filter((d) => d.railId === r.id).map(render)}
              {mine?.kind === 'rail' && mine.railId === r.id && (
                <Ghost
                  left={mine.start * MODULE_PX}
                  top={8}
                  width={mine.width * MODULE_PX}
                  height={RAIL_HEIGHT_PX - 16}
                  valid={mine.valid}
                />
              )}
            </RailRow>
          ))}
          {showWires && (
            <svg
              data-testid="wires"
              className="pointer-events-none absolute left-0 top-0 z-10"
              width={wires.width}
              height={wires.height}
              dangerouslySetInnerHTML={{ __html: wiresToSvg(wires) }}
            />
          )}
        </div>
        {mountW > 0 && (
          <div>
            <div className="mb-1 text-xs text-slate-500">{t('board.mounting')}</div>
            <div
              ref={mountRef}
              data-mount-panel={panel.id}
              data-testid="mount"
              className="relative border border-slate-400 bg-slate-50"
              style={{ width: mountW, height: mountH }}
            >
              {panel.devices.filter((d) => d.railId === null).map(render)}
              {mine?.kind === 'mount' && (
                <Ghost
                  left={mine.x * MM_PX}
                  top={mine.y * MM_PX}
                  width={mine.w * MM_PX}
                  height={mine.h * MM_PX}
                  valid={mine.valid}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function RailRow({
  panelId,
  rail,
  children,
}: {
  panelId: number;
  rail: PanelModel['rails'][number];
  children: React.ReactNode;
}) {
  const { setNodeRef } = useDroppable({ id: `rail-${rail.id}` });
  const ticks = [];
  for (let i = 0; i <= rail.capacity; i += 6) ticks.push(i);
  return (
    <div
      ref={setNodeRef}
      data-testid="rail"
      data-rail-id={rail.id}
      data-panel-id={panelId}
      className="relative border border-slate-400 bg-slate-50"
      style={{ width: rail.capacity * MODULE_PX, height: RAIL_HEIGHT_PX }}
    >
      <div
        className="absolute inset-x-0 bg-slate-300"
        style={{ top: RAIL_HEIGHT_PX / 2 - 4, height: 8 }}
      />
      {ticks.map((i) => (
        <span
          key={i}
          className="absolute top-0 border-l border-slate-300 pl-0.5 text-[9px] text-slate-400"
          style={{ left: i * MODULE_PX }}
        >
          {i}
        </span>
      ))}
      {children}
    </div>
  );
}
