// Realistic mock for numeric scores only. Text recommendations are generated
// server-side by GPT-4o Vision (with a fallback on the backend if unavailable).

export type AnalysisScores = {
  global_score: number;
  texture: number;
  radiance: number;
  imperfections: number;
};

function clamp(v: number, min = 30, max = 98) {
  return Math.max(min, Math.min(max, Math.round(v)));
}

function rand(seed: number, min: number, max: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  const frac = x - Math.floor(x);
  return Math.round(min + frac * (max - min));
}

const AGE_BASE: Record<string, number> = {
  "<25": 90,
  "25-40": 82,
  "40-60": 72,
  "60+": 64,
};

export function generateScores(profile?: {
  age_range?: string | null;
  environment?: string | null;
  priority?: string | null;
}): AnalysisScores {
  const seed = Date.now() % 1000;
  const age = profile?.age_range || "25-40";
  const env = (profile?.environment || "").toLowerCase();
  const prio = (profile?.priority || "").toLowerCase();

  const base = AGE_BASE[age] ?? 80;

  let texture = clamp(base - 2 + rand(seed + 2, -6, 8));
  let radiance = clamp(base - 4 + rand(seed + 3, -8, 10));
  let imperfections = clamp(base - 6 + rand(seed + 4, -10, 10));

  // Environment adjustments
  if (env.includes("urbain") || env.includes("pollu")) {
    radiance -= 6;
    imperfections -= 4;
  }
  if (env.includes("sec") || env.includes("climatis")) {
    texture -= 5;
  }
  if (env.includes("humide")) {
    imperfections -= 3;
  }

  // Priority slightly lowers the matching score so recos target it
  if (prio.includes("éclat") || prio.includes("eclat")) radiance -= 4;
  if (prio.includes("ridule")) texture -= 4;
  if (prio.includes("imperfection")) imperfections -= 5;
  if (prio.includes("sensib")) texture -= 3;

  texture = clamp(texture);
  radiance = clamp(radiance);
  imperfections = clamp(imperfections);

  const global_score = Math.round(texture * 0.34 + radiance * 0.33 + imperfections * 0.33);

  return { global_score, texture, radiance, imperfections };
}
