import { useStore } from 'zustand';
import type { BoardState, BoardStore } from './model/store';

export function useBoard<T>(store: BoardStore, selector: (s: BoardState) => T): T {
  return useStore(store, selector);
}

export function useIsNarrow(): boolean {
  const q = typeof window !== 'undefined' ? window.matchMedia('(max-width: 767px)') : null;
  return useStoreMedia(q);
}

import { useSyncExternalStore } from 'react';

function useStoreMedia(q: MediaQueryList | null): boolean {
  return useSyncExternalStore(
    (cb) => {
      q?.addEventListener('change', cb);
      return () => q?.removeEventListener('change', cb);
    },
    () => q?.matches ?? false,
    () => false,
  );
}
