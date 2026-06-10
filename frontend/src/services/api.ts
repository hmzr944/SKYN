import { storage } from "@/src/utils/storage";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL;
const TOKEN_KEY = "skyn_session_token";
const PENDING_REPORTS_KEY = "skyn_pending_reports";

async function authHeader(): Promise<Record<string, string>> {
  const token = await storage.secureGet(TOKEN_KEY, "");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function setToken(token: string) {
  await storage.secureSet(TOKEN_KEY, token);
}

export async function clearToken() {
  await storage.secureRemove(TOKEN_KEY);
}

export async function getToken(): Promise<string | null> {
  const t = await storage.secureGet(TOKEN_KEY, "");
  return t ? (t as string) : null;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(await authHeader()),
    ...((init.headers as Record<string, string>) || {}),
  };
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  googleSession: (session_id: string) =>
    request<{ session_token: string; user: any }>("/api/auth/google/session", {
      method: "POST",
      body: JSON.stringify({ session_id }),
    }),
  appleSession: (
    identity_token: string,
    apple_user_id: string,
    email?: string,
    full_name?: string,
  ) =>
    request<{ session_token: string; user: any }>("/api/auth/apple/session", {
      method: "POST",
      body: JSON.stringify({ identity_token, apple_user_id, email, full_name }),
    }),
  me: () => request<any>("/api/auth/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
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
