import { useCallback, useState } from "react";
import type { ToastData, ToastKind } from "@/components/Toast";

/** Show a notice: what happened, whether it is a failure, and optionally its heading. */
export type PushToast = (message: string, kind: ToastKind, title?: string) => void;

/** Transient notifications rendered by <Toast>; each dismisses itself after a few seconds. */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  const pushToast = useCallback<PushToast>((message, kind, title) => {
    setToasts((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, message, kind, title },
    ]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, pushToast, dismissToast };
}
