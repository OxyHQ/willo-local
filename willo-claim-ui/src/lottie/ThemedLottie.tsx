// Web equivalent of packages/frontend/components/themed-lottie.tsx from the
// main Willo monorepo. Same usage pattern (crop once, recolor by reading
// live theme colors, render) — "live theme colors" there means React's
// useTheme() from @oxy.so/bloom/theme; here, since this app has no React
// Native runtime and doesn't use BloomThemeProvider (see
// scripts/generate-bloom-theme.ts's doc comment), it means the resolved
// values of the Bloom CSS custom properties wired in via bloom-theme.css,
// read straight off the document root. Rendered with lottie-web (a
// standard web Lottie player) instead of lottie-react-native.
import { useEffect, useMemo, useRef } from "react";
import lottie from "lottie-web";
import { recolorLottie, type LottieRgb } from "./lottie-recolor";
import { parseRgb } from "./parse-rgb";
import { THEME_COLOR_ROLE_TO_CSS_VAR, type ThemedAnimation } from "./connect-home-assistant-animation";

interface ThemedLottieProps {
  animation: ThemedAnimation;
  loop?: boolean;
  className?: string;
}

/**
 * Reads the CURRENT resolved value of each CSS custom property `animation`'s
 * colorRoles maps to (`getComputedStyle(document.documentElement)` — the
 * web equivalent of reading `useTheme().colors[role]` on the RN side) and
 * builds the same kind of 0..1 RGB palette `recolorLottie` expects.
 *
 * Computed once, not re-read on a live `prefers-color-scheme` flip: this
 * screen has no theme picker and no user session, so the one case that
 * would matter (the OS/browser's color scheme changing while the device is
 * already on this screen) is rare enough, and a boot-sequence stage change
 * re-renders this component anyway (see App.tsx), that a full page reload
 * remains the simplest correct fix — matching this whole app's
 * "no client-side routing, no persisted state" design.
 */
function readLiveBloomPalette(colorRoles: ThemedAnimation["colorRoles"]): Map<string, LottieRgb> {
  const palette = new Map<string, LottieRgb>();
  const computed = getComputedStyle(document.documentElement);
  for (const [sourceHex, role] of Object.entries(colorRoles)) {
    const cssVariable = THEME_COLOR_ROLE_TO_CSS_VAR[role];
    const rawValue = computed.getPropertyValue(cssVariable).trim();
    const rgb = parseRgb(rawValue);
    if (!rgb) {
      console.warn(`ThemedLottie: could not parse Bloom colour var "${cssVariable}" (${rawValue}); keeping ${sourceHex}.`);
      continue;
    }
    palette.set(sourceHex, [rgb.r / 255, rgb.g / 255, rgb.b / 255]);
  }
  return palette;
}

export function ThemedLottie({ animation, loop = true, className }: ThemedLottieProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const source = useMemo(() => {
    const palette = readLiveBloomPalette(animation.colorRoles);
    return recolorLottie(animation.source, palette);
  }, [animation]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const instance = lottie.loadAnimation({
      container,
      renderer: "svg",
      loop,
      autoplay: true,
      animationData: source,
    });
    return () => instance.destroy();
  }, [source, loop]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ aspectRatio: `${source.w} / ${source.h}` }}
    />
  );
}
