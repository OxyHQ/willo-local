// Ported nearly verbatim from packages/frontend/components/lottie-crop.ts
// in the main Willo monorepo (OxyHQ/Willo) — pure JSON manipulation, no
// lottie-react-native runtime dependency in the original either, only its
// `AnimationObject` type, swapped for a local equivalent (see
// lottie-types.ts) since this app renders with lottie-web, not
// lottie-react-native.
import type { LottieAnimation } from "./lottie-types";

/** A rectangle in the animation's own canvas coordinates. */
export interface LottieCropBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

const CROPPED_COMPOSITION_ID = "cropped-composition";

/**
 * Shrinks an animation's canvas to `box`, so the drawing fills whatever the
 * animation is sized to instead of floating in the exporter's empty margins.
 *
 * The original layers move into a precomp, and one precomp layer shifted by
 * the box's origin shows it; every renderer clips to the canvas, so anything
 * outside the box is hidden on web and native alike.
 */
export function cropLottie(animation: LottieAnimation, box: LottieCropBox): LottieAnimation {
  return {
    ...animation,
    w: box.width,
    h: box.height,
    assets: [...animation.assets, { id: CROPPED_COMPOSITION_ID, layers: animation.layers }],
    layers: [
      {
        ddd: 0,
        ind: 1,
        ty: 0,
        refId: CROPPED_COMPOSITION_ID,
        sr: 1,
        ks: {
          o: { a: 0, k: 100 },
          r: { a: 0, k: 0 },
          p: { a: 0, k: [-box.x, -box.y, 0] },
          a: { a: 0, k: [0, 0, 0] },
          s: { a: 0, k: [100, 100, 100] },
        },
        ao: 0,
        w: animation.w,
        h: animation.h,
        ip: animation.ip,
        op: animation.op,
        st: 0,
        bm: 0,
      },
    ],
  };
}
