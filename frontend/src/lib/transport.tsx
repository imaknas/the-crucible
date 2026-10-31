"use client";
import { createContext, useContext } from "react";

/**
 * How the app opens WebSockets — injectable so hooks can be unit-tested with
 * a fake socket instead of replacing the global WebSocket.
 *
 * The app uses the default (a real WebSocket) and needs no provider; tests
 * wrap a hook in <TransportProvider value={fakeFactory}>.
 */
export type SocketFactory = (url: string) => WebSocket;

/** WebSocket.OPEN, without reading the (possibly replaced) global. */
export const SOCKET_OPEN = 1;

const defaultFactory: SocketFactory = (url) => new WebSocket(url);

const TransportContext = createContext<SocketFactory>(defaultFactory);

export const TransportProvider = TransportContext.Provider;

export function useSocketFactory(): SocketFactory {
  return useContext(TransportContext);
}

export function isOpen(socket: WebSocket | null | undefined): boolean {
  return socket?.readyState === SOCKET_OPEN;
}

/** WebSocket.CONNECTING. */
export const SOCKET_CONNECTING = 0;

/**
 * Whether the socket `current()` returns is open, waiting up to `timeoutMs`
 * while it is still connecting. A message sent right after a thread opens
 * finds its socket a moment from ready; refusing it then said "Not sent".
 */
export async function whenOpen(
  current: () => WebSocket | null | undefined,
  timeoutMs = 5000,
  stepMs = 50,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (current()?.readyState === SOCKET_CONNECTING && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, stepMs));
  }
  return isOpen(current());
}
