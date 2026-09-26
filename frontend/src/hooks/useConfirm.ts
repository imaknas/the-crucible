import { useCallback, useState } from "react";

export interface ConfirmRequest {
  title: string;
  message: string;
}

/**
 * Promise-based confirmation: `await confirm(title, message)` resolves true
 * or false once the user answers the <ConfirmDialog> this hook drives.
 */
export function useConfirm() {
  const [pending, setPending] = useState<
    (ConfirmRequest & { resolve: (accepted: boolean) => void }) | null
  >(null);

  const confirm = useCallback(
    (title: string, message: string): Promise<boolean> =>
      new Promise((resolve) => setPending({ title, message, resolve })),
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
