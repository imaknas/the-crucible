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
