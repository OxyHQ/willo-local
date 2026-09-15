import { QRCodeSVG } from 'qrcode.react'
import './App.css'
import { useOrchestratorStatus, type OrchestratorStage } from './useOrchestratorStatus'

const STAGE_MESSAGE: Record<OrchestratorStage, string> = {
  onboarding: 'Preparando Willo Green…',
  syncing: 'Sincronizando…',
  'awaiting-pairing': 'Generando código de emparejamiento…',
  paired: 'Emparejado',
}

function App() {
  const status = useOrchestratorStatus()

  return (
    <main className="screen">
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
