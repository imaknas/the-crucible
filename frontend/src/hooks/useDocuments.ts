import { useCallback, useState } from "react";
import * as api from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { PushToast } from "@/hooks/useToasts";

/**
 * The files attached to the next message.
 *
 * An upload stores the file on the thread, both as a document the turn can
 * name and in its search index; frames then carry only the names
 * (`document_names`), not the full text once per model. Attachments belong
 * to one turn and one thread: sending clears them, and so does opening
 * another thread (they used to ride along into it).
 */
export function useDocuments({
  threadId,
  pushToast,
  onUploaded,
}: {
  threadId: string | null;
  pushToast: PushToast;
  /** A file was stored on this thread (e.g. turn document search on). */
  onUploaded?: (filename: string) => void;
}) {
  const [names, setNames] = useState<string[]>([]);
  // The file being uploaded, shown as a pending chip.
  const [uploading, setUploading] = useState<string | null>(null);

  // Another thread: its attachments are not this one's. Adjusted during
  // render, the way React documents resetting state on a prop change.
  const [forThread, setForThread] = useState(threadId);
  if (forThread !== threadId) {
    setForThread(threadId);
    setNames([]);
    setUploading(null);
  }

  const attach = useCallback(
    async (file: File) => {
      if (!threadId) return;
      setUploading(file.name);
      try {
        const data = await api.uploadDocument(file, threadId);
        // Re-uploading a filename replaces the stored file: one chip per name.
        setNames((prev) => [...prev.filter((n) => n !== data.filename), data.filename]);
        onUploaded?.(data.filename);
      } catch (error) {
        pushToast(errorMessage(error, `Couldn't upload ${file.name}`), "error", "Upload failed");
      } finally {
        setUploading(null);
      }
    },
    [threadId, pushToast, onUploaded],
  );

  const remove = useCallback((name: string) => setNames((prev) => prev.filter((n) => n !== name)), []);
  const clear = useCallback(() => setNames([]), []);

  return { names, uploading, attach, remove, clear };
}
