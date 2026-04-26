/**
 * hooks/useHardwareSocket.ts — Hook WebSocket para telemetria de hardware.
 *
 * Conecta ao endpoint ws://localhost:8000/ws/hardware e retorna as
 * métricas mais recentes em tempo real (atualização a cada ~2 s).
 *
 * Reconexão automática com backoff exponencial (máx. 30 s).
 */
import { useState, useEffect, useRef, useCallback } from 'react'

export interface HardwareMetrics {
    cpu: number
    ram: number
    ram_used_gb: number
    ram_total_gb: number
    disk: number
    disk_used_gb: number
    disk_total_gb: number
    cpu_temp: number | null
}

const DEFAULT_URL = 'ws://localhost:8000/ws/hardware'
const MAX_DELAY = 30_000

export function useHardwareSocket(url = DEFAULT_URL): HardwareMetrics | null {
    const [metrics, setMetrics] = useState<HardwareMetrics | null>(null)
    const wsRef = useRef<WebSocket | null>(null)
    const retryDelay = useRef(1_000)
    const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
    const mounted = useRef(true)

    const connect = useCallback(() => {
        if (!mounted.current) return

        const ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => {
            retryDelay.current = 1_000
        }

        ws.onmessage = (event: MessageEvent) => {
            try {
                setMetrics(JSON.parse(event.data as string) as HardwareMetrics)
            } catch {
                // ignora payload malformado
            }
        }

        ws.onclose = (event: CloseEvent) => {
            wsRef.current = null
            if (!mounted.current || event.code === 1000) return
            retryTimer.current = setTimeout(() => {
                retryDelay.current = Math.min(retryDelay.current * 2, MAX_DELAY)
                connect()
            }, retryDelay.current)
        }

        ws.onerror = () => {
            ws.close()
        }
    }, [url])

    useEffect(() => {
        mounted.current = true
        connect()
        return () => {
            mounted.current = false
            if (retryTimer.current) clearTimeout(retryTimer.current)
            wsRef.current?.close(1000)
        }
    }, [connect])

    return metrics
}
