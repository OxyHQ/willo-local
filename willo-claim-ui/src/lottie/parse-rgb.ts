// Ported nearly verbatim from @oxy.so/bloom's
// node_modules/@oxy.so/bloom/src/theme/color-utils.ts (`parseRgba`/`parseRgb`)
// — not imported directly because @oxy.so/bloom/theme's barrel also exports
// BloomThemeProvider, which imports 'react-native' at module scope; even
// importing one unrelated named export from that barrel would evaluate that
// module graph and fail in this plain Vite app (confirmed: a deep import
// path to bypass the barrel is blocked by @oxy.so/bloom's package.json
// "exports" map). This is small and self-contained enough to copy exactly,
// matching how lottie-crop.ts/lottie-recolor.ts are ported.
export interface RgbChannels {
  r: number;
  g: number;
  b: number;
}

interface RgbaChannels extends RgbChannels {
  a: number;
}

/** Parse a `#rgb`/`#rrggbb`/`rgb()`/`rgba()` color string, or `null` if it can't be parsed. */
export function parseRgba(color: string): RgbaChannels | null {
  const trimmed = color.trim();
  if (trimmed.startsWith("#")) {
    let hex = trimmed.slice(1);
    if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
    if (hex.length !== 6) return null;
    const r = parseInt(hex.slice(0, 2), 16);
    const g = parseInt(hex.slice(2, 4), 16);
    const b = parseInt(hex.slice(4, 6), 16);
    if ([r, g, b].some((v) => Number.isNaN(v))) return null;
    return { r, g, b, a: 1 };
  }
  const match = /rgba?\(([^)]+)\)/i.exec(trimmed);
  if (!match || match[1] === undefined) return null;
  const raw = match[1].split(/[\s,/]+/).filter(Boolean);
  if (raw.length < 3) return null;
  const [r, g, b] = raw.map(Number);
  if (r === undefined || g === undefined || b === undefined) return null;
  if ([r, g, b].some((v) => Number.isNaN(v))) return null;
  const alphaText = raw[3];
  if (alphaText === undefined) return { r, g, b, a: 1 };
  const a = alphaText.endsWith("%") ? Number(alphaText.slice(0, -1)) / 100 : Number(alphaText);
  if (Number.isNaN(a)) return null;
  return { r, g, b, a };
}

/**
 * Parse a color string into its RGB channels, or `null` if it can't be parsed.
 * Discards any alpha the string carried.
 */
export function parseRgb(color: string): RgbChannels | null {
  const parsed = parseRgba(color);
  if (!parsed) return null;
  return { r: parsed.r, g: parsed.g, b: parsed.b };
}
