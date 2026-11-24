import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';
import type { SimResult } from '../../../api/endpoints';
import { buildDiagram, NODE_W, type DiagramNode } from '../model/diagram';
import { energize, type Energized } from '../model/energize';
import type { BoardStore } from '../model/store';
import { useBoard } from '../useStore';

const COLOR: Record<string, string> = {
  feeder: '#e2e8f0',
  bus: '#cbd5e1',
  chain: '#e9d5ff',
  rcd: '#fde68a',
  breaker: '#dbeafe',
  other: '#f1f5f9',
};

type Data = { node: DiagramNode; unbound: boolean; power?: Energized };

export const SOURCE_COLOR: Record<string, string> = {
  grid: '#16a34a',
  generator: '#ea580c',
  inverter: '#2563eb',
  pv: '#ca8a04',
};

function DeviceNode({ data, selected }: NodeProps<Node<Data>>) {
  const n = data.node;
  return (
    <div
      data-testid="diagram-node"
      data-node-id={n.id}
      data-power={data.power ? (data.power.powered ? 'on' : 'off') : undefined}
      data-source={data.power?.source ?? undefined}
      className={`rounded border px-2 py-1 text-xs ${selected ? 'ring-2 ring-blue-600' : ''} ${data.unbound ? 'border-dashed border-slate-500' : 'border-slate-700'}`}
      style={{
        width: NODE_W,
        background: COLOR[n.kind],
        ...(data.power && !data.power.powered ? { opacity: 0.45, filter: 'grayscale(1)' } : {}),
        ...(data.power?.powered && data.power.source
          ? { boxShadow: `0 0 0 2px ${SOURCE_COLOR[data.power.source] ?? '#16a34a'}` }
          : {}),
      }}
    >
      <Handle type="target" position={n.kind === 'breaker' ? Position.Top : Position.Left} />
      <div className="truncate font-semibold">
        {n.tag && <span className="mr-1">{n.tag}</span>}
        {n.title}
      </div>
      <div className="truncate text-[10px] text-slate-600">{n.subtitle}</div>
      <div className="truncate text-[10px]">{n.load}</div>
      {n.kind === 'feeder' && data.power?.source && (
        <div data-testid="feeder-source" className="truncate text-[10px] font-semibold">
          ⚡ {data.power.source}
        </div>
      )}
      <Handle
        type="source"
        position={n.kind === 'rcd' || n.kind === 'bus' ? Position.Bottom : Position.Right}
      />
    </div>
  );
}

const nodeTypes = { device: DeviceNode };

export function DiagramView({
  store,
  panelId,
  sim = null,
}: {
  store: BoardStore;
  panelId: number;
  sim?: SimResult | null;
}) {
  const panel = useBoard(store, (s) => s.panels[panelId]);
  const products = useBoard(store, (s) => s.products);
  const groups = useBoard(store, (s) => s.groups);
  const selection = useBoard(store, (s) => s.selection);

  const diagram = useMemo(
    () => (panel ? buildDiagram(panel, products, groups) : { nodes: [], edges: [] }),
    [panel, products, groups],
  );

  const power = useMemo(
    () => (panel ? energize(panel, diagram, sim) : new Map<string, Energized>()),
    [panel, diagram, sim],
  );

  const nodes: Node<Data>[] = diagram.nodes.map((n) => ({
    id: n.id,
    type: 'device',
    position: { x: n.x, y: n.y },
    data: { node: n, unbound: n.kind === 'breaker' && n.groupId === null, power: power.get(n.id) },
    selected: selection.includes(n.id),
    draggable: true,
    connectable: false,
    deletable: n.deviceId !== null,
  }));
  const edges: Edge[] = diagram.edges.map((e) => {
    const s = power.get(e.target);
    return {
      ...e,
      type: 'smoothstep',
      ...(s
        ? {
            animated: s.powered,
            style: {
              stroke: s.powered ? (SOURCE_COLOR[s.source ?? ''] ?? '#16a34a') : '#cbd5e1',
              strokeWidth: 2,
            },
          }
        : {}),
    };
  });

  return (
    <div className="h-full w-full" data-testid="diagram">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        deleteKeyCode={null}
        onNodeClick={(e, n) => {
          if (n.data.node.deviceId)
            store
              .getState()
              .select(n.id, e.shiftKey || e.ctrlKey || e.metaKey ? 'toggle' : 'replace');
        }}
        onNodeDragStop={(_e, n) =>
          store.getState().setNodePosition(panelId, n.id, {
            x: Math.round(n.position.x),
            y: Math.round(n.position.y),
          })
        }
        onPaneClick={() => store.getState().clearSelection()}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
