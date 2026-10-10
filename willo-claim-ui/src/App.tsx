import { Admonition } from '@oxy.so/bloom/admonition';
import { AnimatedCheck, type AnimatedCheckRef } from '@oxy.so/bloom/animated-check';
import { Card } from '@oxy.so/bloom/card';
import { fontFamilies } from '@oxy.so/bloom/fonts';
import { atoms as a } from '@oxy.so/bloom/styles';
import { H1, Lead, Muted, Text } from '@oxy.so/bloom/typography';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useRef } from 'react';
import { View } from 'react-native';
import { connectHomeAssistantAnimation } from './lottie/connect-home-assistant-animation';
import { ThemedLottie } from './lottie/ThemedLottie';
import { useOrchestratorStatus, type OrchestratorStage } from './useOrchestratorStatus';

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
};

function ClaimCard({ claimCode }: { claimCode: string }) {
  return (
    <Card radius="radius-20">
      <View style={[a.align_center, a.gap_md, a.p_xl]}>
        {/* marginSize draws the QR's white quiet zone inside the SVG, so the
            code stays scannable on a dark card too. */}
        <QRCodeSVG value={claimCode} size={220} marginSize={4} />
        <Text variant="title-1-semibold" style={{ fontFamily: fontFamilies.mono }}>
          {claimCode}
        </Text>
        <Muted style={[a.text_center, { maxWidth: 416 }]}>
          Abre la app de Willo y escanea el código, o escríbelo a mano.
        </Muted>
      </View>
    </Card>
  );
}

/** Mounted on the transition to `paired`, which is the moment the check should draw. */
function PairedCheck() {
  const check = useRef<AnimatedCheckRef>(null);
  useEffect(() => {
    check.current?.play();
  }, []);
  return <AnimatedCheck ref={check} size={64} />;
}

function App() {
  const status = useOrchestratorStatus();

  return (
    <View style={[a.flex_1, a.align_center, a.justify_center, a.gap_xl, a.p_xl]}>
      {/* The same "waiting to connect Home Assistant" animation the main
          Willo app plays at this exact moment in its own onboarding — see
          src/lottie/connect-home-assistant-animation.ts — for visual
          continuity between the app side and the device side of one flow. */}
      <ThemedLottie animation={connectHomeAssistantAnimation} />
      <H1>Willo</H1>

      {status.error !== null ? (
        <Admonition type="error">
          Algo salió mal. Vuelve a intentarlo o contacta con soporte de Willo.
        </Admonition>
      ) : (
        <>
          <Lead style={a.text_center}>{STAGE_MESSAGE[status.stage]}</Lead>

          {status.stage === 'awaiting-pairing' && status.claimCode !== null && (
            <ClaimCard claimCode={status.claimCode} />
          )}

          {status.stage === 'paired' && <PairedCheck />}
        </>
      )}
    </View>
  );
}

export default App;
