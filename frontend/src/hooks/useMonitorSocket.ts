/**
 * hooks/useMonitorSocket.ts — Hook WebSocket para alertas proativos do Alfred.
 *
 * Conecta ao endpoint ws://localhost:8000/ws/notifications e chama
 * `onAlert` sempre que um alerta chegar do MonitorService.
 *
 * Reconexão automática com backoff exponencial (máx. 30 s) quando a
 * conexão cair inesperadamente.
 *
 * Formato dos alertas recebidos:
 *   { type, category, title, message, timestamp, value }
 */
import { useEffect, useRef, useCallback } from 'react'

export interface MonitorAlert {
  type:      'error' | 'warning' | 'info' | 'success'
  category:  'cpu' | 'ram' | 'battery' | 'file' | string
  title:     string
  message:   string
  timestamp: string
  value:     number | string
}

interface UseMonitorSocketOptions {
  /** Endereço completo do WebSocket (sem /api proxy — conexão direta). */
  url?: string
  /** Chamado com cada alerta recebido do servidor. */
  onAlert: (alert: MonitorAlert) => void
  /** Se false, não conecta (útil p/ desabilitar em produção sem backend). */
  enabled?: boolean
}

const DEFAULT_URL = 'ws://localhost:8000/ws/notifications'
const MAX_DELAY   = 30_000  // ms

export function useMonitorSocket({
  url = DEFAULT_URL,
  onAlert,
  enabled = true,
}: UseMonitorSocketOptions): void {
  const wsRef      = useRef<WebSocket | null>(null)
  const retryDelay = useRef<number>(1_000)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted    = useRef<boolean>(true)
  // Keep onAlert stable across re-renders
  const onAlertRef = useRef(onAlert)
  onAlertRef.current = onAlert

  const connect = useCallback(() => {
    if (!mounted.current || !enabled) return

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      retryDelay.current = 1_000   // reset backoff on successful connection
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const alert: MonitorAlert = JSON.parse(event.data as string)
        onAlertRef.current(alert)
      } catch {
        // Ignora mensagens malformadas
      }
    }

    ws.onclose = (event: CloseEvent) => {
      wsRef.current = null
      // Reconecta apenas se foi fechamento inesperado (não um close normal = 1000)
      if (!mounted.current) return
      if (event.code === 1000) return  // encerramento limpo (ex: shutdown do servidor)

      retryTimer.current = setTimeout(() => {
        retryDelay.current = Math.min(retryDelay.current * 2, MAX_DELAY)
        connect()
      }, retryDelay.current)
    }

    ws.onerror = () => {
      // onclose será disparado logo após — reconexão já cuidada lá
      ws.close()
    }
  }, [url, enabled]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    mounted.current = true
    if (enabled) connect()

    return () => {
      mounted.current = false
      if (retryTimer.current) clearTimeout(retryTimer.current)
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounted')
        wsRef.current = null
      }
    }
  }, [connect, enabled])
}
