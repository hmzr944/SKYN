import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient } from "@supabase/supabase-js";

const SUPABASE_URL = "https://axpyatbjvvoxjtwkrhwu.supabase.co";
const SUPABASE_ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF4cHlhdGJqdnZveGp0d2tyaHd1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA5MTQ5MTEsImV4cCI6MjA5NjQ5MDkxMX0.tY10xXJm4-W4GTABsbFovHAd6wNiQLNjrT_3w4Olvhw";

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    storage: AsyncStorage,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: Platform.OS === "web",
  },
});

// Cloud backup: best-effort. Silently no-ops if tables don't exist.
export async function pushReportToSupabase(report: {
  id: string;
  user_id: string;
  global_score: number;
  texture: number;
  radiance: number;
  imperfections: number;
  recommendations: string[];
  created_at: string;
}) {
  try {
    await supabase.from("skyn_reports").insert(report);
  } catch {
    /* no-op */
  }
}
