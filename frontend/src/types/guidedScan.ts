/**
 * Contrat de POST /api/analyze/guided.
 * Miroir du dict renvoye par le handler dans backend/server.py.
 *
 * Deux origines distinctes, composees a l'endpoint (voir server.py) :
 *   - `lesions`/`zone_scores` : le suivi multi-vue confirme
 *     (skyn_engine.v2.multiview.orchestrer_scan) — la SEULE source fiable
 *     pour la Memoire de peau, deja alimentee avant l'ajout ci-dessous.
 *   - tout le reste (`routine`, `skin_type`, `concerns`...) : un second
 *     calcul (analyze_multi, la meme fonction que /analyze/v2), plafonne
 *     aux 3 premieres vues. Facultatif dans ce type parce qu'il peut,
 *     tres rarement, etre absent (echec de detection sur ces 3 vues
 *     precises) sans faire echouer tout le scan — voir server.py.
 */
import type {
  ConcernKey,
  FaceBox,
  LesionType,
  Routine,
  SkinType,
  ZoneKey,
} from "@/src/types/analysis";

export type GuidedScanStatus = "TARGET_REACHED" | "MAX_REACHED" | "NEED_MORE_VIEWS";

export interface GuidedLesion {
  x: number;
  y: number;
  type: LesionType;
  zone: string;
  n_observations: number;
  /** Coherence photometrique des observations de cette piste, 0..1. */
  coherence_photo: number;
  /** Score d'evidence a 5 dimensions ayant fait passer le vote-gate, 0..1. */
  evidence: number;
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
  zone_scores: Partial<Record<ZoneKey, number>>;

  // --- Second calcul (analyze_multi), facultatif — voir l'en-tete. -----
  global_score?: number;
  skin_type?: SkinType;
  skin_type_confidence?: number;
  phototype?: string;
  phototype_label?: string;
  severity_level?: 0 | 1 | 2 | 3 | 4;
  severity_label?: string;
  gags_score?: number;
  diagnosis?: string;
  summary?: string;
  concerns?: Record<ConcernKey, number>;
  top_concerns?: ConcernKey[];
  drivers?: Record<string, string>;
  hormonal_pattern?: boolean;
  routine?: Routine;
  cautions?: string[];
  face_box?: FaceBox;
}
