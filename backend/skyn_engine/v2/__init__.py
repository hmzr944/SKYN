"""SKYN Engine v2.

Analyse cutanee multi-zones. Point d'entree public : `analyze_face`.

L'import est paresseux pour que les sous-modules restent chargeables
individuellement (tests, outils de calibration) sans tirer tout le moteur.
"""

__all__ = ["analyze_face", "FaceAnalysis"]


def __getattr__(name):
    if name in ("analyze_face", "FaceAnalysis"):
        from . import pipeline
        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
