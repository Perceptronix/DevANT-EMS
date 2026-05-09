import { useEffect, useRef, useState } from 'react'

type OnMessageFn = (data: any) => void

export default function useSSE(url?: string, onMessage?: OnMessageFn) {
  const esRef = useRef<EventSource | null>(null)
  const onMessageRef = useRef<OnMessageFn | undefined>(onMessage)
  const [connected, setConnected] = useState(false)
  const [lastRaw, setLastRaw] = useState<string | null>(null)
  const [eventLog, setEventLog] = useState<Array<{ t: string; data: string }>>([])
  const closedByUser = useRef(false)
  const connectingRef = useRef(false)

  // Keep onMessage callback current without triggering effect
  useEffect(() => {
    onMessageRef.current = onMessage
  }, [onMessage])

  useEffect(() => {
    if (!url) {
      // Clean up when url becomes undefined
      if (esRef.current) {
        closedByUser.current = true
        esRef.current.close()
        esRef.current = null
        setConnected(false)
      }
      return
    }

    // Block duplicate connections for the same URL
    if (esRef.current) {
      return
    }

    closedByUser.current = false
    connectingRef.current = true

    try {
      const es = new EventSource(url)
      esRef.current = es

      es.addEventListener('open', () => {
        setConnected(true)
      })

      const handle = (type: string, ev: MessageEvent) => {
        const text = ev.data
        setLastRaw(text)
        setEventLog((l) => [{ t: type, data: text }, ...l].slice(0, 100))
        try {
          const parsed = JSON.parse(text)
          onMessageRef.current?.(parsed)
        } catch (e) {
          // ignore parse errors
        }
      }

      es.addEventListener('update', (ev) => handle('update', ev as MessageEvent))
      es.addEventListener('message', (ev) => handle('message', ev as MessageEvent))
      es.addEventListener('error', () => {
        setConnected(false)
        if (!closedByUser.current && esRef.current) {
          esRef.current.close()
        }
        esRef.current = null
        connectingRef.current = false
        // Browser EventSource will auto-reconnect; no manual reconnect needed
      })
    } catch (e) {
      setConnected(false)
      esRef.current = null
      connectingRef.current = false
    }

    return () => {
      closedByUser.current = true
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      setConnected(false)
    }
  }, [url])

  const close = () => {
    closedByUser.current = true
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setConnected(false)
  }

  return { connected, lastRaw, eventLog, close }
}
