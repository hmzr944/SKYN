/**
 * L'historique unifie des scans — Dashboard, Suivi et ProgressTimeline en
 * ont chacun besoin, et lisaient jusqu'ici exclusivement scanStore.ts
 * (local, alimente par le seul flux /camera). Le scan guide, parcours
 * principal depuis cette session, n'ecrit que dans skin_memory (backend) :
 * ces trois ecrans restaient donc vides pour quiconque n'utilise que lui.
 *
 * skin_memory devient ici la source canonique (voir GET /api/scans) ; les
 * entrees scanStore existantes sont fusionnees pour l'affichage — un
 * residu historique du flux /camera, jamais reecrit, jamais recalcule.
 * Aucune double-ecriture n'est introduite : /camera continue d'ecrire dans
 * scanStore comme avant, /camera-guided continue d'ecrire dans skin_memory
 * comme avant. Seule la LECTURE est unifiee.
 */
import { api } from "@/src/services/api";
import { listScans as listLegacyScans } from "@/src/services/scanStore";
import type { ConcernKey, SkinType } from "@/src/types/analysis";
import type { MemoryScan } from "@/src/types/skinMemory";

export type ScanOrigin = "legacy" | "memory";

export interface UnifiedScan {
  id: string;
  date: string;
  global_score: number | null;
  diagnosis: string | null;
  skin_type: SkinType | null;
  severity_level: number | null;
  lesion_total: number;
  top_concerns: ConcernKey[];
  origin: ScanOrigin;
  /** Uniquement pour origin === "memory" — sert a router vers le Bilan de
   * sa Phase (/phase-summary) plutot que vers scan-result.tsx, qui a
   * besoin d'un FaceAnalysis complet (routine, quality, drivers...) que
   * skin_memory ne conserve pas et ne doit pas dupliquer. */
  period_id?: string;
  /** Faux uniquement pour un scan legacy elague (voir scanStore.ts) — un
   * scan memoire reste toujours consultable via le Bilan de sa Phase. */
  detailed: boolean;
}

function fromMemory(s: MemoryScan): UnifiedScan {
  const lesionTotal = Object.values(s.lesion_counts ?? {}).reduce((a, b) => a + b, 0);
  return {
    id: s.id,
    date: s.created_at,
    global_score: s.global_score,
    diagnosis: s.diagnosis,
    skin_type: (s.skin_type as SkinType) ?? null,
    severity_level: s.severity_level,
    lesion_total: lesionTotal,
    top_concerns: (s.top_concerns as ConcernKey[]) ?? [],
    origin: "memory",
    period_id: s.period_id,
    detailed: true,
  };
}

export async function listUnifiedScans(): Promise<UnifiedScan[]> {
  const [legacy, memory] = await Promise.all([
    listLegacyScans(),
    // Echec reseau silencieux ici : un historique qui degrade au residu
    // local vaut mieux qu'un ecran qui casse — les autres ecrans de
    // memoire (skin-map, phase-history) ont deja leur propre etat d'erreur.
    api.listMemoryScans().catch(() => [] as MemoryScan[]),
  ]);

  const unified: UnifiedScan[] = [
    ...memory.map(fromMemory),
    ...legacy.map((s) => ({
      id: s.id,
      date: s.date,
      global_score: s.global_score,
      diagnosis: s.diagnosis || null,
      skin_type: s.skin_type,
      severity_level: s.severity_level,
      lesion_total: s.lesion_total,
      top_concerns: s.top_concerns,
      origin: "legacy" as const,
      detailed: s.detailed,
    })),
  ];

  return unified.sort((a, b) => +new Date(b.date) - +new Date(a.date));
}
