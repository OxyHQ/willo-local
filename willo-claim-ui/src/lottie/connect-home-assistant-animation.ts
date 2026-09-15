// Crop box and colorRoles ported verbatim from packages/frontend/data/
// lottie-animations.ts's `connectHomeAssistant` entry in the main Willo
// monorepo — the exact animation the main app's own onboarding plays at
// this same moment (waiting to connect Home Assistant), for visual
// continuity between the app side and the device side of the same flow.
import { cropLottie } from "./lottie-crop";
import rawAnimation from "./connect-home-assistant.json";
import type { LottieAnimation } from "./lottie-types";

/**
 * The Bloom `ThemeColors` role names the original animation's colorRoles
 * mapping uses (packages/frontend/data/lottie-animations.ts). Kept as the
 * same vocabulary as the source mapping, resolved to a CSS custom property
 * below (this app has no `useTheme()` — no React Native runtime here — so
 * it reads Bloom's live theme values from the DOM instead; see
 * ThemedLottie.tsx).
 */
export type ThemeColorRole =
  | "backgroundSecondary"
  | "border"
  | "textSecondary"
  | "textTertiary"
  | "primary"
  | "secondary"
  | "success"
  | "error";

/**
 * Role → CSS custom property, matching @oxy.so/bloom's own
 * `buildColorsFromPreset` (src/theme/build-theme.ts) field-for-field:
 *   backgroundSecondary: g('surface')            → --surface
 *   border:              g('border')             → --border
 *   textSecondary:       g('muted-foreground')    → --muted-foreground
 *   primary/secondary/success/error: g(<same name>)
 *
 * ONE deliberate approximation: Bloom's real `textTertiary` is
 * `r.outline` — the M3 colour engine's "outline" role, which is NOT one of
 * the canonical tokens `theme.css`/scripts/generate-bloom-theme.ts expose as
 * a static CSS variable (it only exists inside the JS colour engine, which
 * isn't safely importable here without pulling in `react-native` — see
 * parse-rgb.ts's doc comment for why). `--muted-foreground` is the closest
 * available real Bloom token doing the same "muted secondary/tertiary text"
 * job, so `textTertiary` maps to it too. Both source hex values the
 * original animation maps to `textTertiary` therefore render identically to
 * `textSecondary` here — a real, documented divergence from the app's exact
 * pixels, not an oversight.
 */
export const THEME_COLOR_ROLE_TO_CSS_VAR: Readonly<Record<ThemeColorRole, string>> = {
  backgroundSecondary: "--surface",
  border: "--border",
  textSecondary: "--muted-foreground",
  textTertiary: "--muted-foreground",
  primary: "--primary",
  secondary: "--secondary",
  success: "--success",
  error: "--error",
};

export interface ThemedAnimation {
  source: LottieAnimation;
  /** Each colour the animation was exported with (lowercase `#rrggbb`) and the Bloom role that replaces it. */
  colorRoles: Readonly<Record<string, ThemeColorRole>>;
}

export const connectHomeAssistantAnimation: ThemedAnimation = {
  source: cropLottie(rawAnimation as unknown as LottieAnimation, { x: 58, y: 36, width: 276, height: 243 }),
  colorRoles: {
    "#f8f9fa": "backgroundSecondary",
    "#dfe1e5": "border",
    "#bdc1c6": "textTertiary",
    "#bec1c6": "textTertiary",
    "#9aa0a6": "textSecondary",
    "#4285f4": "primary",
    "#fabb05": "secondary",
    "#34a853": "success",
    "#fa4335": "error",
  },
};
