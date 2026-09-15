// Ported nearly verbatim from packages/frontend/components/lottie-recolor.ts
// in the main Willo monorepo (OxyHQ/Willo) — pure JSON manipulation, no
// lottie-react-native runtime dependency in the original either, only its
// `AnimationObject` type, swapped for a local equivalent (see
// lottie-types.ts) since this app renders with lottie-web, not
// lottie-react-native.
import type { LottieAnimation } from "./lottie-types";

/** A Lottie colour's red, green and blue channels, each 0..1. */
export type LottieRgb = readonly [number, number, number];

/** Source colour (lowercase `#rrggbb`) → the colour that replaces it. */
export type LottiePalette = ReadonlyMap<string, LottieRgb>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumberArray(value: unknown): value is number[] {
  return Array.isArray(value) && value.every((item) => typeof item === "number");
}

/** Lowercase `#rrggbb` for Lottie colour channels, which run 0..1. */
export function lottieColorToHex(channels: readonly number[]): string {
  return `#${channels
    .slice(0, 3)
    .map((channel) => Math.round(channel * 255).toString(16).padStart(2, "0"))
    .join("")}`;
}

/**
 * Every helper below returns its input by reference when nothing inside it
 * changed, so only the objects on the path to a recoloured value are copied
 * and the untouched bulk of the animation (paths, transforms) is shared.
 */
function updateKey(node: unknown, key: string, update: (value: unknown) => unknown): unknown {
  if (!isRecord(node) || !(key in node)) {
    return node;
  }
  const value = update(node[key]);
  return value === node[key] ? node : { ...node, [key]: value };
}

function mapShared(items: unknown, update: (item: unknown) => unknown): unknown {
  if (!Array.isArray(items)) {
    return items;
  }
  const mapped = items.map(update);
  return mapped.every((item, index) => item === items[index]) ? items : mapped;
}

/** A Lottie property's `k` is either a static value or a list of keyframes holding it in `s` (and `e` in older exports). */
function recolorAnimatable(property: unknown, recolorValue: (value: unknown) => unknown): unknown {
  return updateKey(property, "k", (value) => {
    const isKeyframed = Array.isArray(value) && value.some(isRecord);
    if (!isKeyframed) {
      return recolorValue(value);
    }
    return mapShared(value, (keyframe) => updateKey(updateKey(keyframe, "s", recolorValue), "e", recolorValue));
  });
}

function recolorColor(channels: unknown, palette: LottiePalette): unknown {
  if (!isNumberArray(channels) || channels.length < 3) {
    return channels;
  }
  const replacement = palette.get(lottieColorToHex(channels));
  return replacement ? [...replacement, ...channels.slice(3)] : channels;
}

/** Gradient stops are one flat array: `stopCount` × [offset, r, g, b], then the opacity stops. */
function recolorGradientStops(stops: unknown, stopCount: number, palette: LottiePalette): unknown {
  if (!isNumberArray(stops) || stops.length < stopCount * 4) {
    return stops;
  }
  let recolored: number[] | undefined;
  for (let stop = 0; stop < stopCount; stop++) {
    const channelsStart = stop * 4 + 1;
    const replacement = palette.get(lottieColorToHex(stops.slice(channelsStart, channelsStart + 3)));
    if (replacement) {
      recolored ??= [...stops];
      recolored.splice(channelsStart, 3, ...replacement);
    }
  }
  return recolored ?? stops;
}

function recolorShape(shape: unknown, palette: LottiePalette): unknown {
  if (!isRecord(shape)) {
    return shape;
  }
  switch (shape.ty) {
    case "gr":
      return updateKey(shape, "it", (items) => mapShared(items, (item) => recolorShape(item, palette)));
    case "fl":
    case "st":
      return updateKey(shape, "c", (color) => recolorAnimatable(color, (value) => recolorColor(value, palette)));
    case "gf":
    case "gs":
      return updateKey(shape, "g", (gradient) => {
        if (!isRecord(gradient) || typeof gradient.p !== "number") {
          return gradient;
        }
        const stopCount = gradient.p;
        return updateKey(gradient, "k", (stops) => recolorAnimatable(stops, (value) => recolorGradientStops(value, stopCount, palette)));
      });
    default:
      return shape;
  }
}

function recolorLayers(layers: unknown, palette: LottiePalette): unknown {
  return mapShared(layers, (layer) => updateKey(layer, "shapes", (shapes) => mapShared(shapes, (shape) => recolorShape(shape, palette))));
}

/**
 * Swaps the colours of a Lottie animation's fills, strokes and gradients
 * (static or animated, in top-level layers and precomps) for the ones in
 * `palette`. Colours not in the palette are left as exported. Text and solid
 * layers are not recoloured.
 *
 * Done on the JSON rather than with a player's built-in colour filters
 * because the web renderer this app uses (lottie-web) doesn't reliably
 * support runtime colour filtering the way this needs. Returns `animation`
 * itself when no colour matched.
 */
export function recolorLottie(animation: LottieAnimation, palette: LottiePalette): LottieAnimation {
  if (palette.size === 0) {
    return animation;
  }
  const layers = recolorLayers(animation.layers, palette);
  const assets = mapShared(animation.assets, (asset) => updateKey(asset, "layers", (assetLayers) => recolorLayers(assetLayers, palette)));
  if (layers === animation.layers && assets === animation.assets) {
    return animation;
  }
  return {
    ...animation,
    layers: Array.isArray(layers) ? layers : animation.layers,
    assets: Array.isArray(assets) ? assets : animation.assets,
  };
}
