import { useEffect, useRef } from 'react'
import { getApiToken } from '../api/client'
import { useDashboardStore } from '../store'
import type { Statistics } from '../types'

/**
 * Subscribes to the SSE statistics-stream endpoint.
 *
 * Pushes real-time stats into the Zustand store every time the server emits.
 * Auto-reconnects on connection loss with exponential back-off.
 */
export function useSSE(): void {
  const setStats = useDashboardStore((s) => s.setStats)
  const retryDelay = useRef(1_000)
  const esRef = useRef<EventSource | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let destroyed = false

    function connect() {
      if (destroyed) return

      // EventSource doesn't support custom headers, so pass token as a query
      // param on the URL when running in dev mode (proxied by Vite).
      const token = getApiToken()
      const url = token
        ? `/api/statistics-stream?token=${encodeURIComponent(token)}`
        : '/api/statistics-stream'

      const es = new EventSource(url)
      esRef.current = es

      es.onopen = () => {
        retryDelay.current = 1_000 // reset back-off
      }

      es.onmessage = (event) => {
        try {
          const stats: Statistics = JSON.parse(event.data)
          setStats(stats)
        } catch {
          // ignore malformed frames
        }
      }

      es.onerror = () => {
        es.close()
        esRef.current = null
        if (!destroyed) {
          timerRef.current = setTimeout(() => {
            retryDelay.current = Math.min(retryDelay.current * 2, 60_000)
            connect()
          }, retryDelay.current)
        }
      }
    }

    connect()

    return () => {
      destroyed = true
      esRef.current?.close()
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [setStats])
}
