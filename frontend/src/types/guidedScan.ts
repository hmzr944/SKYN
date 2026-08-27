/**
 * Contrat de POST /api/analyze/guided (v0, experimental — parallele a
 * /api/analyze/v2, pas un remplacement).
 * Miroir du dict renvoye par le handler dans backend/server.py, construit a
 * partir de `ScanResult` dans backend/skyn_engine/v2/multiview.py.
 */

export type GuidedScanStatus = "TARGET_REACHED" | "MAX_REACHED" | "NEED_MORE_VIEWS";

export interface GuidedLesion {
  x: number;
  y: number;
  type: string;
  n_observations: number;
}

export interface ViewDiagnostic {
  /** -1 (profil gauche) .. 0 (face) .. 1 (profil droit). */
  yaw_proxy: number;
  roll_deg: number;
}

export interface GuidedScanResponse {
  lesions: GuidedLesion[];
  frames_received: number;
  usable_views: number;
  stop_reason: string;
  status: GuidedScanStatus;
  view_diagnostics: ViewDiagnostic[];
}
