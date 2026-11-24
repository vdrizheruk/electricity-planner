import { useDraggable } from '@dnd-kit/core';
import { useTranslation } from 'react-i18next';
import type { Group } from '../model/types';

function Item({
  group,
  onAdd,
  readOnly,
}: {
  group: Group;
  onAdd: (g: Group) => void;
  readOnly: boolean;
}) {
  const { attributes, listeners, setNodeRef } = useDraggable({
    id: `group-${group.id}`,
    data: { type: 'group', group },
    disabled: readOnly,
  });
  return (
    <li
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      data-testid="unplaced-item"
      data-group-id={group.id}
      onClick={() => !readOnly && onAdd(group)}
      className="cursor-grab rounded border border-amber-400 bg-amber-50 px-2 py-1 text-xs"
      style={{ touchAction: 'none' }}
    >
      <b>
        {group.curve}
        {group.breaker_a}
      </b>{' '}
      {group.name}
    </li>
  );
}

export function UnplacedList({
  groups,
  onAdd,
  readOnly,
}: {
  groups: Group[];
  onAdd: (g: Group) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <h2 className="mb-1 font-semibold">
        {t('board.unplaced')} ({groups.length})
      </h2>
      {groups.length === 0 ? (
        <p className="text-xs text-slate-500">{t('board.unplacedEmpty')}</p>
      ) : (
        <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
          {groups.map((g) => (
            <Item key={g.id} group={g} onAdd={onAdd} readOnly={readOnly} />
          ))}
        </ul>
      )}
    </div>
  );
}
