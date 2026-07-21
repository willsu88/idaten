import type { GearItem, GearSuggestion } from "./types";

/**
 * Brand accent colors for the generated shoe cards (no photo uploaded).
 * A curated map for common running brands — just data, so it ships fine in an
 * open-source repo — with a deterministic hue fallback for anything else.
 */
const BRAND_COLORS: Array<[RegExp, string]> = [
  [/new balance/i, "#cf0a2c"],
  [/adidas/i, "#1c2b5e"],
  [/\bnike\b/i, "#ff5c00"],
  [/\basics\b/i, "#001e62"],
  [/\bhoka\b/i, "#0072ce"],
  [/saucony/i, "#e21836"],
  [/brooks/i, "#00629b"],
  [/\bon\b|\bon cloud/i, "#3f3f46"],
  [/salomon/i, "#d5001c"],
  [/mizuno/i, "#003da5"],
  [/altra/i, "#c8102e"],
  [/li[- ]?ning/i, "#c8102e"],
  [/puma/i, "#1a1a1a"],
  [/under armour/i, "#1d1d1d"],
  [/topo/i, "#2e7d32"],
  [/kiprun|decathlon/i, "#0082c3"],
];

export function brandColor(name: string): string {
  for (const [re, color] of BRAND_COLORS) {
    if (re.test(name)) return color;
  }
  // Deterministic fallback hue from the name; fixed s/l keeps text readable.
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return `hsl(${h}, 55%, 38%)`;
}

/** "New Balance 1080v14" -> "NB", "ON" -> "ON", "Salomon XA 3D Pro" -> "S" */
export function brandInitials(name: string): string {
  const trimmed = name.trim();
  // Known multi-word brands get both initials; everything else only the first
  // word is the brand — the second is usually the model ("adidas Adizero").
  const multi = /^(new balance|under armour|la sportiva)/i.exec(trimmed);
  if (multi) {
    return multi[1]
      .split(/\s+/)
      .map((w) => w[0])
      .join("")
      .toUpperCase();
  }
  const first = trimmed.split(/\s+/)[0];
  return (first.length <= 3 ? first : first[0]).toUpperCase();
}

export function activeShoes(gear: GearItem[]): GearItem[] {
  return gear.filter((g) => g.gear_type === "Shoes" && g.status === "active");
}

export function shoeName(gear: GearItem[], uuid: string | null): string | null {
  return gear.find((g) => g.uuid === uuid)?.name ?? null;
}

/** "plan:long_run" -> "long runs"; "pace:easy" -> "easy-paced runs" */
export function bucketLabel(s: GearSuggestion): string {
  const [kind, value] = s.bucket.split(":");
  const pretty = value.replace(/_run$/, "").replace(/_/g, " ");
  return kind === "plan" ? `${pretty} runs` : `${pretty}-paced runs`;
}
