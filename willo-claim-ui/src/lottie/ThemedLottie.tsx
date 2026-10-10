// Web equivalent of packages/frontend/components/themed-lottie.tsx from the
// main Willo monorepo. Same usage pattern (crop once, recolor from the live
// Bloom theme via useTheme(), render) — rendered with lottie-web (a standard
// web Lottie player) instead of lottie-react-native.
import { parseRgb, useTheme, type ThemeColors } from '@oxy.so/bloom/theme';
import lottie from 'lottie-web';
import { useEffect, useMemo, useRef } from 'react';
import { recolorLottie, type LottieRgb } from './lottie-recolor';
import type { ThemedAnimation } from './connect-home-assistant-animation';

interface ThemedLottieProps {
  animation: ThemedAnimation;
  loop?: boolean;
}

/** Each source colour → the 0..1 RGB of the Bloom theme colour its role names. */
function buildPalette(
  colorRoles: ThemedAnimation['colorRoles'],
  colors: ThemeColors,
): Map<string, LottieRgb> {
  const palette = new Map<string, LottieRgb>();
  for (const [sourceHex, role] of Object.entries(colorRoles)) {
    const rgb = parseRgb(colors[role]);
    if (!rgb) {
      console.warn(
        `ThemedLottie: could not parse Bloom colour "${role}" (${colors[role]}); keeping ${sourceHex}.`,
      );
      continue;
    }
    palette.set(sourceHex, [rgb.r / 255, rgb.g / 255, rgb.b / 255]);
  }
  return palette;
}

export function ThemedLottie({ animation, loop = true }: ThemedLottieProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { colors } = useTheme();

  // Re-derived whenever Bloom's palette changes (e.g. the OS flips between
  // light and dark while this screen is open).
  const source = useMemo(
    () => recolorLottie(animation.source, buildPalette(animation.colorRoles, colors)),
    [animation, colors],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const instance = lottie.loadAnimation({
      container,
      renderer: 'svg',
      loop,
      autoplay: true,
      animationData: source,
    });
    return () => instance.destroy();
  }, [source, loop]);

  // lottie-web renders into a real DOM node, so this stays a plain <div>.
  return (
    <div
      ref={containerRef}
      style={{ width: 'min(220px, 50vw)', aspectRatio: `${source.w} / ${source.h}` }}
    />
  );
}
