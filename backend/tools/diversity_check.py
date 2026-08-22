"""Mesure la diversite des recommandations produites par le moteur.

But : verifier objectivement le reproche fait a l'application — "les produits
sont les memes pour tout le monde". On simule une population d'utilisateurs
plausible et on compte combien de routines DISTINCTES le moteur sait produire,
ainsi que la part occupee par la routine la plus frequente.

On compare le meme protocole applique a v1 (selection de paragraphes) et a v2
(correspondance sur vecteur mesure).

Usage : python3 tools/diversity_check.py
"""
from __future__ import annotations

import importlib.util
import os
import random
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

N = 4000
SEED = 11

AGES = ["<25", "25-40", "40-60", "60+"]
ENVS = ["Urbain", "Sec", "Humide", "Variable"]
PRIOS = ["Éclat", "Ridules", "Imperfections", "Sensibilité"]
BUDGETS = ["petit", "moyen", "large"]
EXPS = ["debutant", "intermediaire", "avance"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
def simulate_v1(n=N):
    """v1 : trois paragraphes choisis dans une bibliotheque de modeles."""
    es = _load("es_v1", os.path.join(BACKEND, "skyn_engine", "expert_system.py"))
    rng = random.Random(SEED)

    def clamp(v, lo=30, hi=98):
        return int(round(max(lo, min(hi, v))))

    outs, diags, scores = Counter(), Counter(), []
    for _ in range(n):
        lap = rng.gauss(7.5, 2.2)
        grad = rng.gauss(14, 4)
        Lm, Ls = rng.gauss(150, 18), rng.gauss(17, 4.5)
        dark = abs(rng.gauss(0.07, 0.03))
        tx = clamp(100 - ((lap - 3) / 13) * 58 - ((grad - 8) / 16) * 6)
        rd = clamp(30 + ((Lm - 90) / 90) * 60 - max(0, Ls - 14) * 1.5)
        im = clamp(95 - (dark - 0.04) * 450)
        red = max(0.0, rng.gauss(3.0, 2.0))
        im = clamp(im - rng.randint(0, 5) * 4)

        age, env, prio = rng.choice(AGES), rng.choice(ENVS), rng.choice(PRIOS)
        pl = prio.lower()
        if "clat" in pl:
            rd = clamp(rd - 4)
        if "ridule" in pl:
            tx = clamp(tx - 4)
        if "imperfection" in pl:
            im = clamp(im - 4)

        scores.append(clamp(tx * .34 + rd * .33 + im * .33))
        p = es.ProfileCtx(age, env, prio)
        m = {"texture": tx, "radiance": rd, "imperfections": im, "redness": red}
        d = es.diagnose(m, p)
        outs[tuple(es.recommend(m, p, d))] += 1
        diags[d] += 1
    return outs, diags, scores


# --------------------------------------------------------------------------
def simulate_v2(n=N):
    """v2 : routine construite par correspondance sur le vecteur mesure."""
    from skyn_engine.v2.phenotype import Phenotype, ZoneStats
    from skyn_engine.v2.lesions import LesionReport
    from skyn_engine.v2.concerns import build_fingerprint
    from skyn_engine.v2.matching import build_routine, _load_catalog

    catalog = _load_catalog()
    rng = random.Random(SEED)
    outs, diags, scores = Counter(), Counter(), []

    PHOTOTYPES = [("I", "Tres claire", 60), ("II", "Claire", 48),
                  ("III", "Intermediaire", 34), ("IV", "Mate", 19),
                  ("V", "Brune", -10), ("VI", "Foncee", -45)]

    for _ in range(n):
        # Phenotype tire dans des plages plausibles et non correlees
        sebum_t = min(1.0, max(0.0, rng.betavariate(2.0, 2.2)))
        sebum_u = min(1.0, max(0.0, sebum_t - abs(rng.gauss(0.2, 0.18))))
        dryness = min(1.0, max(0.0, rng.betavariate(1.8, 3.0) * (1 - sebum_t)))
        redness = min(1.0, max(0.0, rng.betavariate(1.8, 3.2)))
        pores = min(1.0, max(0.0, rng.betavariate(2.0, 2.6)))
        uneven = min(1.0, max(0.0, rng.betavariate(2.0, 2.4)))
        delta = sebum_t - sebum_u

        if sebum_t >= .55 and sebum_u >= .45:
            st = "grasse"
        elif delta >= .18 and sebum_t >= .35:
            st = "mixte"
        elif max(sebum_t, sebum_u) < .30 and dryness >= .45:
            st = "seche"
        else:
            st = "normale"

        code, label, ita = rng.choice(PHOTOTYPES)
        ph = Phenotype(
            skin_type=st, skin_type_confidence=0.8,
            phototype=code, phototype_label=label, ita_deg=float(ita),
            sensitive=redness > 0.55, sebum_t=sebum_t, sebum_u=sebum_u,
            shine_delta=delta, dryness=dryness, redness_global=redness,
            pore_load=pores, unevenness=uneven,
            zones={"joue_g": ZoneStats("joue_g", 0, 0, 0, 0, 0, 0, 0, 0)},
        )

        # Charge lesionnelle : beaucoup de peaux nettes, une minorite severe
        sev = rng.choices([0, 1, 2, 3, 4], weights=[28, 30, 22, 14, 6])[0]
        base = sev * rng.uniform(2, 7)
        counts = {
            "comedon": int(base * rng.uniform(0.3, 1.2)),
            "papule": int(base * rng.uniform(0.2, 0.9)),
            "pustule": int(base * rng.uniform(0.0, 0.4)),
            "marque_rouge": int(base * rng.uniform(0.0, 0.7)),
            "marque_brune": int(base * rng.uniform(0.0, 0.5)),
        }
        zones = ["front", "joue_g", "joue_d", "menton", "machoire_g", "nez"]
        per_zone, density = {}, {}
        for z in zones:
            share = rng.uniform(0, 1)
            per_zone[z] = {k: int(v * share / len(zones) * 2) for k, v in counts.items()}
            density[z] = sum(per_zone[z].values()) * rng.uniform(0.2, 0.6)
        lr = LesionReport(
            lesions=[], counts=counts, per_zone=per_zone, density=density,
            gags_score=float(sev * 8), severity_level=sev,
            severity_label=["peau_nette", "acne_legere", "acne_moderee",
                            "acne_severe", "acne_tres_severe"][sev],
            inflammatory_ratio=0.5, dominant_zones=zones[:2],
            hormonal_pattern=rng.random() < 0.2,
        )

        profile = {
            "age_range": rng.choice(AGES), "environment": rng.choice(ENVS),
            "priority": rng.choice(PRIOS), "budget": rng.choice(BUDGETS),
            "experience": rng.choice(EXPS),
            "pregnant": rng.random() < 0.05,
        }

        fp = build_fingerprint(ph, lr, profile)
        rt = build_routine(fp, ph, profile, catalog=catalog)
        key = tuple(sorted(p.product["id"] for p in (rt.am + rt.pm + rt.weekly)))
        outs[key] += 1
        diags[f"{st} / {lr.severity_label}"] += 1
        scores.append(fp.global_score)
    return outs, diags, scores


# --------------------------------------------------------------------------
def report(title, outs, diags, scores):
    tot = sum(outs.values())
    top = sorted(outs.values(), reverse=True)
    scores = sorted(scores)
    n = len(scores)
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")
    print(f"  sorties distinctes        : {len(outs)}")
    print(f"  part de la sortie n1      : {100 * top[0] / tot:.1f} %")
    print(f"  part du top 3             : {100 * sum(top[:3]) / tot:.1f} %")
    print(f"  part du top 5             : {100 * sum(top[:5]) / tot:.1f} %")
    print(f"  sorties vues une seule fois: {sum(1 for v in outs.values() if v == 1)}")
    print(f"  score global min/med/max  : {scores[0]} / {scores[n // 2]} / {scores[-1]}")
    print(f"  bande contenant 80 % users: {scores[int(n * .1)]} - {scores[int(n * .9)]}"
          f"  ({scores[int(n * .9)] - scores[int(n * .1)]} pts)")
    print("  diagnostic le plus frequent:")
    for d, c in diags.most_common(3):
        print(f"      {100 * c / tot:5.1f} %  {d}")


if __name__ == "__main__":
    o1, d1, s1 = simulate_v1()
    report(f"v1 — selection de paragraphes ({N} utilisateurs simules)", o1, d1, s1)
    o2, d2, s2 = simulate_v2()
    report(f"v2 — correspondance sur vecteur mesure ({N} utilisateurs simules)", o2, d2, s2)

    print(f"\n{'=' * 62}")
    print(f"  routines distinctes : {len(o1)}  ->  {len(o2)}"
          f"   (x{len(o2) / max(1, len(o1)):.1f})")
    t1 = 100 * max(o1.values()) / sum(o1.values())
    t2 = 100 * max(o2.values()) / sum(o2.values())
    print(f"  concentration n1    : {t1:.1f} %  ->  {t2:.1f} %")
    print(f"{'=' * 62}")
