import { useDraggable } from '@dnd-kit/core';
import { MM_PX, MODULE_PX } from '../model/geometry';
import { colorOf, shortName } from '../model/match';
import type { Energized } from '../model/energize';
import type { Device, Group, Product } from '../model/types';

interface Props {
  device: Device;
  panelId: number;
  product: Product | undefined;
  group: Group | undefined;
  selected: boolean;
  invalid: boolean;
  readOnly: boolean;
  energized?: Energized;
  onClick: (id: string, additive: boolean) => void;
}

export function DeviceView({
  device,
  panelId,
  product,
  group,
  selected,
  invalid,
  readOnly,
  energized,
  onClick,
}: Props) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: device.id,
    data: { type: 'device', deviceId: device.id, panelId },
    disabled: readOnly,
  });
  const onRail = device.railId !== null;
  const style: React.CSSProperties = onRail
    ? { left: (device.start ?? 0) * MODULE_PX, width: device.width * MODULE_PX, top: 8, bottom: 8 }
    : {
        left: (device.x ?? 0) * MM_PX,
        top: (device.y ?? 0) * MM_PX,
        width: (device.w ?? 0) * MM_PX,
        height: (device.h ?? 0) * MM_PX,
      };
  const label = group?.name ?? device.label;
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      data-testid="device"
      data-device-id={device.id}
      data-group-id={device.groupId ?? ''}
      data-power={energized ? (energized.powered ? 'on' : 'off') : undefined}
      onClick={(e) => {
        e.stopPropagation();
        onClick(device.id, e.shiftKey || e.ctrlKey || e.metaKey);
      }}
      title={product ? `${product.brand.name} ${product.sku}\n${product.name}` : ''}
      style={{
        ...style,
        backgroundColor: colorOf(product),
        touchAction: 'none',
        ...(energized && !energized.powered ? { opacity: 0.4, filter: 'grayscale(1)' } : {}),
      }}
      className={[
        'absolute select-none overflow-hidden rounded border text-center text-[11px] leading-tight',
        selected ? 'ring-2 ring-blue-600' : '',
        energized?.powered ? 'shadow-[0_0_0_2px_#16a34a]' : '',
        invalid ? 'border-red-600 border-2' : 'border-slate-600',
        isDragging ? 'opacity-30' : '',
        readOnly ? '' : 'cursor-grab',
      ].join(' ')}
    >
      <div className="font-semibold">{product ? shortName(product) : '?'}</div>
      {label && (
        <div
          data-testid="device-label"
          className="mt-1 break-words text-[10px] [writing-mode:vertical-rl] mx-auto max-h-[70px] overflow-hidden"
        >
          {label}
        </div>
      )}
    </div>
  );
}
