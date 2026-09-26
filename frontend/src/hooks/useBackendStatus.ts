import { useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";

export type ConnectionTone = "ok" | "warn" | "error";

/**
 * Whether the app can actually run: backend reachable and at least one API key
 * set. Drives the header status line and the landing view's key warning.
 */
export function useBackendStatus() {
  const [reachable, setReachable] = useState<boolean | null>(null);
  const [keyCount, setKeyCount] = useState(0);

  useEffect(() => {
    api
      .fetchKeyStatus()
      .then((status) => {
        setKeyCount(Object.values(status).filter((v) => v.set).length);
        setReachable(true);
      })
      .catch(() => setReachable(false));
  }, []);

  const connection = useMemo((): { tone: ConnectionTone; label: string } => {
    if (reachable === null) return { tone: "warn", label: "Connecting…" };
    if (!reachable) return { tone: "error", label: "Backend unreachable" };
    if (keyCount === 0) return { tone: "error", label: "No API keys set" };
    return { tone: "ok", label: `${keyCount} ${keyCount === 1 ? "key" : "keys"} · connected` };
  }, [reachable, keyCount]);

  // Unknown (still loading) or unreachable counts as "has keys": the landing
  // view should only nag when the backend positively reports none.
  const hasAnyKey = reachable === null ? null : !reachable || keyCount > 0;

  return { connection, hasAnyKey };
}
