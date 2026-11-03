/**
 * Blind comparison: a turn's answers as "Answer A/B/C", in an order fixed by
 * the turn and the model (the same as the backend's services/votes.py and
 * `crucible vote --show`), with nothing that names the model until the
 * person votes.
 */
import type { TurnCard } from "@/lib/turns";

function utf8(text: string): number[] {
  const bytes: number[] = [];
  for (const ch of text) {
    const c = ch.codePointAt(0)!;
    if (c < 0x80) bytes.push(c);
    else if (c < 0x800) bytes.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else if (c < 0x10000) bytes.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    else bytes.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return bytes;
}

/** 32-bit FNV-1a over the UTF-8 bytes; services/votes._fnv1a computes the same. */
export function fnv1a(text: string): number {
  let h = 0x811c9dc5;
  for (const byte of utf8(text)) {
    h ^= byte;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** The models in the order a blind comparison shows them. */
export function blindOrder(turnId: string, models: string[]): string[] {
  const keyed = [...new Set(models)].map((m) => ({ m, h: fnv1a(`${turnId}:${m}`) }));
  keyed.sort((a, b) => a.h - b.h || (a.m < b.m ? -1 : a.m > b.m ? 1 : 0));
  return keyed.map((k) => k.m);
}

export function letterOf(index: number): string {
  return String.fromCharCode(65 + index);
}

/** The cards as a blind comparison shows them: lettered, in blind order, with no colour, metrics or context. */
export function maskCards(cards: TurnCard[], turnId: string): TurnCard[] {
  const order = blindOrder(
    turnId,
    cards.map((c) => c.model),
  );
  return [...cards]
    .sort((a, b) => order.indexOf(a.model) - order.indexOf(b.model))
    .map((c) => ({
      ...c,
      label: `Answer ${letterOf(order.indexOf(c.model))}`,
      color: null,
      metrics: null,
      context: null,
    }));
}

export const TASK_TYPES = ["general", "coding", "writing", "research", "reasoning", "other"] as const;
export type TaskType = (typeof TASK_TYPES)[number];
