import { storage } from "@/src/utils/storage";
import { supabase } from "@/src/services/supabase";
import type { FaceAnalysis } from "@/src/types/analysis";
import type { GuidedScanResponse } from "@/src/types/guidedScan";

// Vide par defaut : en deploiement mono-hote, l'API et l'app web sont servies
// par la meme origine, et les appels partent en relatif sur /api. Sans ce
// repli, chaque requete viserait "undefined/api/...".
const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";
const PENDING_REPORTS_KEY = "skyn_pending_reports";

/** Drapeau de session invite — demo sans compte. */
export const GUEST_FLAG_KEY = "skyn_guest";

async function authHeader(): Promise<Record<string, string>> {
  const guest = (await storage.getItem(GUEST_FLAG_KEY, "")) as string;
  if (guest === "1") return { Authorization: "Bearer skyn-guest" };
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const buildHeaders = async (): Promise<Record<string, string>> => ({
    "Content-Type": "application/json",
    ...(await authHeader()),
    ...((init.headers as Record<string, string>) || {}),
  });

  let res = await fetch(`${BASE}${path}`, { ...init, headers: await buildHeaders() });
  const guest = (await storage.getItem(GUEST_FLAG_KEY, "")) as string;
  if (res.status === 401 && guest !== "1") {
    await supabase.auth.refreshSession();
    res = await fetch(`${BASE}${path}`, { ...init, headers: await buildHeaders() });
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => request<any>("/api/auth/me"),
  getProfile: () => request<any>("/api/profile"),
  updateProfile: (data: any) =>
    request<any>("/api/profile", { method: "PUT", body: JSON.stringify(data) }),
  createReport: (data: any) =>
    request<any>("/api/reports", { method: "POST", body: JSON.stringify(data) }),
  listReports: () => request<any[]>("/api/reports"),
  getReport: (id: string) => request<any>(`/api/reports/${id}`),
  recommendations: (data: {
    image_base64: string;
    global_score: number;
    texture: number;
    radiance: number;
    imperfections: number;
  }) =>
    request<{ recommendations: string[]; source: string }>(
      "/api/recommendations",
      { method: "POST", body: JSON.stringify(data) },
    ),
  /**
   * Moteur v2 : analyse multi-zones et routine personnalisee.
   * `extraImages` accepte jusqu'a deux angles complementaires (profils), qui
   * exposent des zones que la vue de face aplatit.
   */
  analyzeV2: (image_base64: string, extraImages: string[] = []) =>
    request<FaceAnalysis>("/api/analyze/v2", {
      method: "POST",
      body: JSON.stringify({ image_base64, extra_images: extraImages }),
    }),
  /**
   * Scan multi-vue guide (v0, experimental) : jusqu'a `maxVues` images,
   * arret adaptatif cote serveur des que la mesure est jugee stable (au
   * plus tot a `cibleVues`). Endpoint distinct de /analyze/v2, qui reste
   * inchange.
   */
  analyzeGuided: (
    imagesBase64: string[],
    config: { minVuesUtiles?: number; cibleVues?: number; maxVues?: number } = {},
  ) =>
    request<GuidedScanResponse>("/api/analyze/guided", {
      method: "POST",
      body: JSON.stringify({
        images_base64: imagesBase64,
        min_vues_utiles: config.minVuesUtiles ?? 5,
        cible_vues: config.cibleVues ?? 7,
        max_vues: config.maxVues ?? 9,
      }),
    }),
};

// ===== Offline pending reports =====
type PendingReport = {
  local_id: string;
  global_score: number;
  texture: number;
  radiance: number;
  imperfections: number;
  recommendations: string[];
  created_at: string;
};

export async function queuePendingReport(r: Omit<PendingReport, "local_id" | "created_at">) {
  const raw = await storage.getItem(PENDING_REPORTS_KEY, "[]");
  const list: any[] = JSON.parse((raw as string) || "[]");
  list.push({
    ...r,
    local_id: `local_${Date.now()}`,
    created_at: new Date().toISOString(),
  });
  await storage.setItem(PENDING_REPORTS_KEY, JSON.stringify(list));
}

export async function syncPendingReports(): Promise<number> {
  const raw = await storage.getItem(PENDING_REPORTS_KEY, "[]");
  const list: any[] = JSON.parse((raw as string) || "[]");
  if (!list.length) return 0;
  const remaining: any[] = [];
  let synced = 0;
  for (const r of list) {
    try {
      await api.createReport({
        global_score: r.global_score,
        texture: r.texture,
        radiance: r.radiance,
        imperfections: r.imperfections,
        recommendations: r.recommendations,
      });
      synced += 1;
    } catch {
      remaining.push(r);
    }
  }
  await storage.setItem(PENDING_REPORTS_KEY, JSON.stringify(remaining));
  return synced;
}
