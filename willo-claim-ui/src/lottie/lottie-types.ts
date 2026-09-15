/**
 * Local stand-in for `lottie-react-native`'s `AnimationObject` type — this
 * app renders with `lottie-web` (see ThemedLottie.tsx), not
 * lottie-react-native, so there's no runtime dependency to import the real
 * type from. Shaped to match the exact fields lottie-crop.ts and
 * lottie-recolor.ts (ported from packages/frontend/components/) actually
 * read/write; everything else in a real Lottie JSON export passes through
 * both functions untouched via `...animation`, so this doesn't need to be
 * a complete Lottie schema.
 */
export interface LottieAnimation {
  readonly v?: string;
  readonly fr?: number;
  readonly ip: number;
  readonly op: number;
  readonly w: number;
  readonly h: number;
  readonly nm?: string;
  readonly ddd?: number;
  readonly assets: readonly unknown[];
  readonly layers: readonly unknown[];
  readonly [key: string]: unknown;
}
