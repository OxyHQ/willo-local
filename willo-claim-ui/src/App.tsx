import { QRCodeSVG } from 'qrcode.react'
import './App.css'
import { connectHomeAssistantAnimation } from './lottie/connect-home-assistant-animation'
import { ThemedLottie } from './lottie/ThemedLottie'
import { useOrchestratorStatus, type OrchestratorStage } from './useOrchestratorStatus'

const STAGE_MESSAGE: Record<OrchestratorStage, string> = {
  onboarding: 'Preparando Willo Green…',
  syncing: 'Sincronizando…',
  'awaiting-pairing': 'Generando código de emparejamiento…',
  paired: 'Emparejado',
  // Shown on a device that already had its own real Home Assistant setup
  // before Willo Local ever touched it — see ha_config.py's
  // has_meaningful_existing_configuration() and this repo's README.
  // Deliberately reads as "found and kept your existing setup", not
  // "wiping and starting fresh".
  'existing-install': 'Importando configuración actual…',
}

function App() {
  const status = useOrchestratorStatus()

  return (
    <main className="screen">
      {/* The same "waiting to connect Home Assistant" animation the main
          Willo app plays at this exact moment in its own onboarding — see
          src/lottie/connect-home-assistant-animation.ts — for visual
          continuity between the app side and the device side of one flow.
          Replaces the earlier text-only wordmark placeholder. */}
      <ThemedLottie animation={connectHomeAssistantAnimation} className="logo" />
      <h1 className="wordmark">Willo</h1>

      {status.error !== null ? (
        <p className="statusLine statusLine--error">
          Algo salió mal. Vuelve a intentarlo o contacta con soporte de Willo.
        </p>
      ) : (
        <>
          <p className="statusLine">{STAGE_MESSAGE[status.stage]}</p>

          {status.stage === 'awaiting-pairing' && status.claimCode !== null && (
            <div className="claimCard">
              <div className="qrWrapper">
                <QRCodeSVG value={status.claimCode} size={220} />
              </div>
              <p className="claimCode">{status.claimCode}</p>
              <p className="claimHint">Abre la app de Willo y escanea el código, o escríbelo a mano.</p>
            </div>
          )}

          {status.stage === 'paired' && <p className="pairedCheck">✓</p>}
        </>
      )}
    </main>
  )
}

export default App
