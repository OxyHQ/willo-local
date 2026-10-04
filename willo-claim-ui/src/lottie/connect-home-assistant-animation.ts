// Crop box and colorRoles ported verbatim from packages/frontend/data/
// lottie-animations.ts's `connectHomeAssistant` entry in the main Willo
// monorepo — the exact animation the main app's own onboarding plays at
// this same moment (waiting to connect Home Assistant), for visual
// continuity between the app side and the device side of the same flow.
import type { ThemeColors } from "@oxy.so/bloom/theme";
import rawAnimation from "./connect-home-assistant.json";
import { cropLottie } from "./lottie-crop";
import type { LottieAnimation } from "./lottie-types";

/**
 * The Bloom `ThemeColors` roles the original animation's colorRoles mapping
 * uses (packages/frontend/data/lottie-animations.ts) — read at render time
 * from `useTheme().colors`, exactly as the main app does (see ThemedLottie.tsx).
 */
export type ThemeColorRole = keyof Pick<
  ThemeColors,
  "backgroundSecondary" | "border" | "textSecondary" | "textTertiary" | "primary" | "secondary" | "success" | "error"
>;

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
