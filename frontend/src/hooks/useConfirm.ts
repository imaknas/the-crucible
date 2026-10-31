import { useCallback, useState } from "react";

export interface ConfirmOptions {
  /** The verb on the confirm button ("Delete", "Leave"); a bare "Confirm" says nothing. */
  confirmLabel?: string;
  /** Red confirm button: the action loses something. Default true. */
  destructive?: boolean;
}

export interface ConfirmRequest extends ConfirmOptions {
  title: string;
  message: string;
}

export type Confirm = (title: string, message: string, options?: ConfirmOptions) => Promise<boolean>;

/**
 * Promise-based confirmation: `await confirm(title, message, options)`
 * resolves true or false once the user answers the <ConfirmDialog> this hook
 * drives. Only for questions: information goes in a toast.
 */
export function useConfirm() {
  const [pending, setPending] = useState<(ConfirmRequest & { resolve: (accepted: boolean) => void }) | null>(null);

  const confirm = useCallback<Confirm>(
    (title, message, options = {}) => new Promise((resolve) => setPending({ title, message, ...options, resolve })),
    [],
  );

  const answer = useCallback(
    (accepted: boolean) => {
      pending?.resolve(accepted);
      setPending(null);
    },
    [pending],
  );

  return { confirm, request: pending as ConfirmRequest | null, answer };
}
