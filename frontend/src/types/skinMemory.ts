/**
 * Miroir de backend/skin_memory.py — la memoire persistante Scan -> Period
 * -> SkinChange (chantier 4). Rien ici n'est stocke localement : ces types
 * decrivent uniquement ce que /api/scans, /api/periods* et /api/*-events
 * echangent avec le serveur.
 */

export type ScanSource = "v2" | "guided";
export type PhaseState = "baseline" | "tracking" | "understanding";
export type ChangeDirection = "up" | "down" | "stable";
export type Confidence = "low" | "medium" | "high";
export type ChangeKind = "concern" | "zone" | "lesion_type";

export interface MemoryScan {
  id: string;
  user_id: string;
  period_id: string;
  created_at: string;
  source: ScanSource;
  is_baseline: boolean;
  global_score: number | null;
  concerns: Record<string, number>;
  zone_scores: Record<string, number>;
  lesion_counts: Record<string, number>;
  lesions: unknown[];
  capture_quality: Confidence;
}

export interface Period {
  id: string;
  user_id: string;
  starts_at: string;
  ends_at: string | null;
  opened_by: string;
  baseline_scan_id: string;
  latest_scan_id: string;
}

export type RoutineEventType = "created" | "step_added" | "step_removed" | "step_changed";

export interface RoutineEvent {
  id: string;
  user_id: string;
  period_id: string;
  at: string;
  type: RoutineEventType;
  diff: Record<string, string[]>;
}

export interface ProductEvent {
  id: string;
  user_id: string;
  period_id: string;
  at: string;
  type: "introduced" | "stopped";
  product_id: string;
  moment: "am" | "pm";
}

export interface SkinChangeItem {
  metric: string;
  kind: ChangeKind;
  baseline_value: number;
  latest_value: number;
  direction: ChangeDirection;
  confidence: Confidence;
  attribution: string[] | null;
}

export interface ActivePeriodView {
  period: Period;
  state: PhaseState;
  scans: MemoryScan[];
  routine_events: RoutineEvent[];
  product_events: ProductEvent[];
  changes: SkinChangeItem[];
}
