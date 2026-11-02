import { useCallback, useRef, useState } from "react";
import { fetchHistory } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { TurnCard } from "@/lib/turns";
import type { DiffSide } from "@/lib/diff";

interface Options {
  threadId: string | null;
  /** Full text of replies streamed in this tab, by tree node id. */
  replyTexts: Record<string, string>;
  modelLabel: (id: string) => string;
}

export interface AnswerDiffState {
  open: boolean;
  labels: { a: string; b: string };
  a: DiffSide | null;
  b: DiffSide | null;
  error: string | null;
}

const CLOSED: AnswerDiffState = {
  open: false,
  labels: { a: "", b: "" },
  a: null,
  b: null,
  error: null,
};

/**
 * "Compare with…" on a compare card: the two answers' whole texts, for the
 * diff dialog. A card holding an excerpt is read from its path with the API
 * directly, never through the history tree, so comparing changes neither
 * the path on screen nor what the next message continues.
 */
export function useAnswerDiff({ threadId, replyTexts, modelLabel }: Options) {
  const [state, setState] = useState<AnswerDiffState>(CLOSED);
  // Only the newest comparison's texts are applied.
  const request = useRef(0);

  const label = useCallback(
    (card: TurnCard) => card.label || modelLabel(card.model),
    [modelLabel],
  );

  /** The whole text when this tab already has it, else null. */
  const knownText = useCallback(
    (card: TurnCard): string | null => {
      if (card.full && card.text) return card.text;
      if (card.id && replyTexts[card.id]) return replyTexts[card.id];
      return null;
    },
    [replyTexts],
  );

  const textOf = useCallback(
    async (card: TurnCard): Promise<string> => {
      const known = knownText(card);
      if (known !== null) return known;
      if (!card.id || !threadId)
        throw new Error(`${label(card)}'s answer isn't saved yet.`);
      const { messages } = await fetchHistory(threadId, card.id);
      return messages[messages.length - 1]?.content ?? "";
    },
    [knownText, threadId, label],
  );

  const compare = useCallback(
    (first: TurnCard, second: TurnCard) => {
      const id = ++request.current;
      const labels = { a: label(first), b: label(second) };
      const opened = (a: string, b: string): AnswerDiffState => ({
        open: true,
        labels,
        a: { label: labels.a, model: first.model, text: a },
        b: { label: labels.b, model: second.model, text: b },
        error: null,
      });
      // Both on screen already: no loading state to flash.
      const [knownA, knownB] = [knownText(first), knownText(second)];
      if (knownA !== null && knownB !== null) {
        setState(opened(knownA, knownB));
        return;
      }
      setState({ open: true, labels, a: null, b: null, error: null });
      Promise.all([textOf(first), textOf(second)]).then(
        ([a, b]) => {
          if (id !== request.current) return;
          setState(opened(a, b));
        },
        (e) => {
          if (id !== request.current) return;
          // Our own refusal says why; a failed request says what the backend said.
          const why =
            e instanceof Error && e.name === "Error"
              ? e.message
              : errorMessage(e, "Couldn't load the answers");
          setState({ open: true, labels, a: null, b: null, error: why });
        },
      );
    },
    [label, knownText, textOf],
  );

  const close = useCallback(() => {
    request.current++;
    setState(CLOSED);
  }, []);

  return { ...state, compare, close };
}
