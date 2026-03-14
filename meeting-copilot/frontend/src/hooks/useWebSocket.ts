import { useEffect, useRef, useState, useCallback } from 'react';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

interface UseWebSocketOptions {
  onMessage?: (event: MessageEvent) => void;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
}

export function useWebSocket(url: string, options: UseWebSocketOptions = {}) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(options.reconnectDelay ?? 1000);
  const shouldReconnect = useRef(false);
  const onMessageRef = useRef(options.onMessage);

  useEffect(() => {
    onMessageRef.current = options.onMessage;
  }, [options.onMessage]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus('connecting');
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      reconnectDelay.current = options.reconnectDelay ?? 1000;
    };

    ws.onclose = () => {
      setStatus('disconnected');
      if (shouldReconnect.current) {
        reconnectTimeout.current = setTimeout(() => {
          reconnectDelay.current = Math.min(
            reconnectDelay.current * 2,
            options.maxReconnectDelay ?? 30000
          );
          connect();
        }, reconnectDelay.current);
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onmessage = (event) => {
      onMessageRef.current?.(event);
    };
  }, [url, options.reconnectDelay, options.maxReconnectDelay]);

  const disconnect = useCallback(() => {
    shouldReconnect.current = false;
    if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
    wsRef.current?.close();
  }, []);

  const start = useCallback(() => {
    shouldReconnect.current = true;
    connect();
  }, [connect]);

  const send = useCallback((data: ArrayBuffer | string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  useEffect(() => {
    return () => {
      shouldReconnect.current = false;
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
      wsRef.current?.close();
    };
  }, []);

  return { status, send, start, disconnect };
}
