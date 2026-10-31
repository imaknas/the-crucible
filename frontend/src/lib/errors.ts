/**
 * A failed request, carrying the backend's own explanation (`detail`) when it
 * gave one, so the UI can show why instead of only that it failed.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Throw an ApiError for a non-2xx response: the backend's `detail`, else `fallback`. */
export async function ensureOk(res: Response, fallback: string): Promise<void> {
  if (res.ok) return;
  let detail: string | null = null;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail) && typeof body.detail[0]?.msg === "string") detail = body.detail[0].msg;
    else if (typeof body?.error === "string") detail = body.error;
  } catch {
    // Not JSON: the fallback says enough.
  }
  throw new ApiError(detail ?? `${fallback} (HTTP ${res.status})`, res.status);
}

/** What to tell a person about a failure: an ApiError's explanation, else `fallback`. */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) return `${fallback}: the backend is unreachable.`;
  return fallback;
}
