import { useEffect, useState } from 'react'

export type OrchestratorStage = 'onboarding' | 'syncing' | 'awaiting-pairing' | 'paired'

export interface OrchestratorStatus {
  stage: OrchestratorStage
  claimCode: string | null
  qrDataUrl: string | null
  error: string | null
}

const POLL_INTERVAL_MS = 1000

const INITIAL_STATUS: OrchestratorStatus = {
  stage: 'onboarding',
  claimCode: null,
  qrDataUrl: null,
  error: null,
}

/**
 * Polls the orchestrator's own local GET /status endpoint (served by the
 * same process this page is served from — see orchestrator/willo_orchestrator/server.py)
 * roughly once a second, for as long as this component is mounted.
 *
 * This is a real Effect (synchronising with an external system — the
 * orchestrator process's live state), not derived state, so useEffect is
 * the right tool here. The `ignore` flag guards against a slow response
 * landing after a newer poll already started, or after unmount — without
 * it, an out-of-order response could overwrite fresher state with stale
 * data.
 */
export function useOrchestratorStatus(): OrchestratorStatus {
  const [status, setStatus] = useState<OrchestratorStatus>(INITIAL_STATUS)

  useEffect(() => {
    let ignore = false

    async function poll(): Promise<void> {
      try {
        const response = await fetch('/status')
        if (!response.ok) {
          return
        }
        const data = (await response.json()) as OrchestratorStatus
        if (!ignore) {
          setStatus(data)
        }
      } catch {
        // A transient fetch failure (e.g. the orchestrator restarting
        // Core, momentarily busy) just means this poll is skipped — the
        // next interval tick tries again. Nothing to show the person for
        // one missed poll.
      }
    }

    poll()
    const intervalId = window.setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      ignore = true
      window.clearInterval(intervalId)
    }
  }, [])

  return status
}
