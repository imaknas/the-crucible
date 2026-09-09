import { useSyncExternalStore } from "react";

/**
 * Read a localStorage key as a subscribed external store.
 *
 * `useState` + a mount effect is the obvious way to hydrate from localStorage,
 * but it sets state synchronously inside an effect (cascading render) and a
 * lazy `useState` initializer would instead mismatch SSR. `useSyncExternalStore`
 * is the API built for this: the server snapshot is `null`, the client snapshot
 * is the stored string, and React reconciles the two without a hydration error.
 */
const LOCAL_WRITE_EVENT = "crucible:storage";

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(LOCAL_WRITE_EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(LOCAL_WRITE_EVENT, onChange);
  };
}

export function useStoredValue(key: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => null,
  );
}

/** Write a key and notify same-tab `useStoredValue` subscribers. */
export function writeStoredValue(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    window.dispatchEvent(new Event(LOCAL_WRITE_EVENT));
  } catch {}
}
