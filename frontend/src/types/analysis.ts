/**
 * Contrat de l'analyse renvoyee par POST /api/analyze/v2.
 * Miroir de `FaceAnalysis` dans backend/skyn_engine/v2/pipeline.py.
 */

export type ConcernKey =
  | "acne_active"
  | "comedons"
  | "post_acne_marks"
  | "sebum"
  | "pores"
  | "redness"
  | "sensitivity"
  | "dehydration"
  | "dullness"
  | "pigmentation"
  | "texture"
  | "barrier_damage"
  | "aging";

export type ZoneKey =
  | "front"
  | "glabelle"
  | "tempe_g"
  | "tempe_d"
  | "nez"
  | "joue_g"
  | "joue_d"
  | "sous_yeux_g"
  | "sous_yeux_d"
  | "peri_oral"
  | "menton"
  | "machoire_g"
  | "machoire_d";

export type LesionType =
  | "comedon"
  | "papule"
  | "pustule"
  | "marque_rouge"
  | "marque_brune";

export type SkinType = "grasse" | "mixte" | "normale" | "seche" | "indetermine";

export interface Lesion {
  type: LesionType;
  /** Centre normalise 0..1 sur la boite englobante du visage. */
  x: number;
  y: number;
  radius: number;
  diameter_mm: number;
  zone: string;
  confidence: number;
  redness: number;
  darkness: number;
}

export interface ProductPick {
  id: string;
  name: string;
  brand: string;
  step: "nettoyant" | "serum" | "traitement" | "hydratant" | "protection" | "masque";
  moment: "am" | "pm" | "both";
  price_eur: number | null;
  actives: { inci: string; common?: string | null; pct?: number | null }[];
  family: string | null;
  evidence: { level?: "A" | "B" | "C"; note?: string; source?: string };
  /** Fiche du fabricant. Peut avoir disparu : les marques restructurent. */
  url?: string;
  /** Recherche marchande : aboutit toujours, montre prix et disponibilite. */
  buy_url?: string;
  irritation: number;
  /** Adequation en pourcentage, 0..100. */
  match: number;
  why: string[];
  introduce_week: number;
}

export interface ScheduleStep {
  week: number;
  title: string;
  detail: string;
  products: string[];
}

export interface Routine {
  am: ProductPick[];
  pm: ProductPick[];
  weekly: ProductPick[];
  total_price: number;
  irritation_load: number;
  cautions: string[];
  schedule: ScheduleStep[];
}

export interface ZoneDetail {
  lesions: Partial<Record<LesionType, number>>;
  density_cm2: number;
  shine: number | null;
  redness: number | null;
  hair_ratio: number;
}

export interface Quality {
  blur: number;
  exposure: number;
  clipped: number;
  face_ratio: number;
  roll_deg: number;
  yaw_proxy: number;
  usable: boolean;
  issues: string[];
}

export interface FaceAnalysis {
  ok: boolean;
  engine: string;
  global_score: number;
  confidence: number;
  skin_type: SkinType;
  skin_type_confidence: number;
  phototype: string;
  phototype_label: string;
  ita_deg: number;
  severity_level: 0 | 1 | 2 | 3 | 4;
  severity_label: string;
  gags_score: number;
  diagnosis: string;
  summary: string;
  concerns: Record<ConcernKey, number>;
  top_concerns: ConcernKey[];
  drivers: Record<string, string>;
  lesion_counts: Record<LesionType, number>;
  lesions: Lesion[];
  per_zone: Partial<Record<ZoneKey, ZoneDetail>>;
  zone_scores: Partial<Record<ZoneKey, number>>;
  hormonal_pattern: boolean;
  routine: Routine;
  cautions: string[];
  quality: Quality;
  flags: string[];
  /**
   * La boite du visage dans la photo, en pixels, avec la taille de la photo.
   *
   * Les coordonnees des lesions sont normalisees SUR CETTE BOITE, pas sur
   * l'image : sans elle on ne peut pas les replacer sur la photo. Absente des
   * analyses enregistrees avant son ajout — le rendu doit donc s'en passer.
   */
  face_box?: FaceBox;
  elapsed_ms: number;
}

export interface FaceBox {
  x: number;
  y: number;
  w: number;
  h: number;
  image_w: number;
  image_h: number;
}

/** Libelles francais affichables. */
export const CONCERN_LABEL: Record<ConcernKey, string> = {
  acne_active: "Lésions actives",
  comedons: "Comédons",
  post_acne_marks: "Marques post-acné",
  sebum: "Sébum",
  pores: "Pores dilatés",
  redness: "Rougeurs",
  sensitivity: "Réactivité",
  dehydration: "Déshydratation",
  dullness: "Teint terne",
  pigmentation: "Pigmentation",
  texture: "Grain de peau",
  barrier_damage: "Barrière cutanée",
  aging: "Signes de l'âge",
};

export const ZONE_LABEL: Record<ZoneKey, string> = {
  front: "Front",
  glabelle: "Entre-sourcils",
  tempe_g: "Tempe gauche",
  tempe_d: "Tempe droite",
  nez: "Nez",
  joue_g: "Joue gauche",
  joue_d: "Joue droite",
  sous_yeux_g: "Sous l'œil gauche",
  sous_yeux_d: "Sous l'œil droit",
  peri_oral: "Pourtour de la bouche",
  menton: "Menton",
  machoire_g: "Mâchoire gauche",
  machoire_d: "Mâchoire droite",
};

/**
 * Le type de peau circule en identifiant ASCII cote moteur ; il ne doit jamais
 * s'afficher tel quel ("seche" au lieu de "sèche").
 */
export const SKIN_TYPE_LABEL: Record<SkinType, string> = {
  grasse: "grasse",
  mixte: "mixte",
  normale: "normale",
  seche: "sèche",
  indetermine: "indéterminée",
};

export const LESION_LABEL: Record<LesionType, string> = {
  comedon: "Comédons",
  papule: "Papules",
  pustule: "Pustules",
  marque_rouge: "Marques rouges",
  marque_brune: "Marques brunes",
};

export const STEP_LABEL: Record<ProductPick["step"], string> = {
  nettoyant: "Nettoyant",
  serum: "Sérum",
  traitement: "Traitement",
  hydratant: "Hydratant",
  protection: "Protection solaire",
  masque: "Masque",
};

export const SEVERITY_LABEL: Record<number, string> = {
  0: "Peau nette",
  1: "Acné légère",
  2: "Acné modérée",
  3: "Acné sévère",
  4: "Acné très sévère",
};

/** Niveau de preuve -> intitule lisible. */
export const EVIDENCE_LABEL: Record<string, string> = {
  A: "Preuves cliniques établies",
  B: "Données cliniques limitées",
  C: "Intérêt surtout cosmétique",
};
