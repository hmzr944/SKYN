import { storage } from "@/src/utils/storage";
import { supabase } from "@/src/services/supabase";

export type ProductReco = {
  id: string;
  name: string;
  brand: string;
  step: string;
  step_label: string;
  moment: string;
  moment_label: string;
  why: string;
  key_ingredients: string[];
  price_eur: number;
  image_url: string;
  url: string;
};

// Empty string = same origin (single-host deployment where the backend also
// serves the web build). Set EXPO_PUBLIC_BACKEND_URL for a separate backend.
const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";
const PENDING_REPORTS_KEY = "skyn_pending_reports";

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
  if (res.status === 401) {
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
  analyze: (image_base64: string) =>
    request<{
      detected: boolean;
      low_light: boolean;
      luminance: number;
      global_score: number;
      texture: number;
      radiance: number;
      imperfections: number;
      diagnosis: string;
      recommendations: string[];
      detections: { type: string; x: number; y: number; confidence: number; radius: number }[];
      products: ProductReco[];
      skin_type_detected: string | null;
      skin_type_confidence: number;
      acne_severity_level: number | null;
      acne_severity_label: string | null;
      source: string;
    }>("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ image_base64 }),
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
  products?: ProductReco[];
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
        products: r.products || [],
      });
      synced += 1;
    } catch {
      remaining.push(r);
    }
  }
  await storage.setItem(PENDING_REPORTS_KEY, JSON.stringify(remaining));
  return synced;
}
