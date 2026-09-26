import { useCallback, useState } from "react";
import type { ToastData } from "@/components/Toast";

/** Transient notifications rendered by <Toast>; each dismisses itself after a few seconds. */
export function useToasts() {
  const [toasts, setToasts] = useState<ToastData[]>([]);

  const pushToast = useCallback((message: string, model?: string) => {
    setToasts((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, message, model },
    ]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, pushToast, dismissToast };
}
