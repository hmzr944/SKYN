from fastapi import FastAPI, APIRouter, Header, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
import base64
import json
import re
from datetime import datetime, timezone
import httpx
from jose import jwt as jose_jwt

import skin_memory

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MONGO_URL absent ou "demo" -> base en memoire (mongomock). C'est ce qui
# permet une demo cloud sans compte MongoDB ; les donnees serveur sont alors
# perdues au redemarrage du conteneur. Sans ce repli, le processus refusait de
# demarrer et le deploiement plantait au boot.
mongo_url = os.environ.get('MONGO_URL', 'demo')
if mongo_url == 'demo':
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
else:
    client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'skyn')]

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

app = FastAPI()
api_router = APIRouter(prefix="/api")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://axpyatbjvvoxjtwkrhwu.supabase.co").rstrip("/")
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
SUPABASE_ISSUER = f"{SUPABASE_URL}/auth/v1"


# ============ Models ============
class User(BaseModel):
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Profile(BaseModel):
    user_id: str
    age_range: Optional[str] = None       # "<25" | "25-40" | "40-60" | "60+"
    environment: Optional[str] = None     # "Urbain" | "Sec" | "Humide" | "Variable"
    priority: Optional[str] = None        # "Éclat" | "Ridules" | "Imperfections" | "Sensibilité"
    skin_type: Optional[str] = None       # "Normale" | "Mixte" | "Grasse" | "Sèche"
    goals: List[str] = Field(default_factory=list)  # "Hydratation" | "Anti-âge" | "Éclat" | "Pores"
    onboarded: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProfileUpdate(BaseModel):
    age_range: Optional[str] = None
    environment: Optional[str] = None
    priority: Optional[str] = None
    skin_type: Optional[str] = None
    goals: Optional[List[str]] = None
    onboarded: Optional[bool] = None


class Detection(BaseModel):
    type: str
    x: float
    y: float
    confidence: float
    radius: float


class Report(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    global_score: int
    texture: int
    radiance: int
    imperfections: int
    recommendations: List[str]
    diagnosis: Optional[str] = None
    detections: List[Detection] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReportCreate(BaseModel):
    global_score: int
    texture: int
    radiance: int
    imperfections: int
    recommendations: List[str]
    diagnosis: Optional[str] = None
    detections: List[Detection] = Field(default_factory=list)


# ~6MB of base64 (~4.5MB decoded) — generous for a compressed phone photo
MAX_IMAGE_B64_LEN = 6_000_000


class AnalyzeRequest(BaseModel):
    image_base64: str


class AnalyzeResponse(BaseModel):
    detected: bool
    low_light: bool
    luminance: float
    global_score: int
    texture: int
    radiance: int
    imperfections: int
    diagnosis: str
    recommendations: List[str]
    detections: List[Detection]
    source: str


class RecommendationsRequest(BaseModel):
    image_base64: str
    global_score: int
    texture: int
    radiance: int
    imperfections: int


class RecommendationsResponse(BaseModel):
    recommendations: List[str]
    source: str  # "gpt-4o" | "fallback"


# ============ Auth helpers ============
# In-memory cache of Supabase's JWKS (public keys used to sign access tokens).
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}
_JWKS_CACHE_TTL_SECONDS = 600


async def _get_jwks(force: bool = False) -> List[dict]:
    now = datetime.now(timezone.utc).timestamp()
    if force or not _jwks_cache["keys"] or now - _jwks_cache["fetched_at"] > _JWKS_CACHE_TTL_SECONDS:
        async with httpx.AsyncClient(timeout=10.0) as http:
            try:
                resp = await http.get(SUPABASE_JWKS_URL)
            except httpx.HTTPError as e:
                raise HTTPException(status_code=502, detail=f"Unable to reach Supabase: {e}")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Unable to fetch Supabase signing keys")
        _jwks_cache["keys"] = resp.json().get("keys", [])
        _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


async def verify_supabase_jwt(token: str) -> dict:
    """Validate a Supabase Auth access token against the project's JWKS."""
    try:
        unverified_header = jose_jwt.get_unverified_header(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    kid = unverified_header.get("kid")
    keys = await _get_jwks()
    key = next((k for k in keys if k.get("kid") == kid), None)
    if not key:
        keys = await _get_jwks(force=True)
        key = next((k for k in keys if k.get("kid") == kid), None)
    if not key:
        raise HTTPException(status_code=401, detail="Signing key not found")

    try:
        claims = jose_jwt.decode(
            token,
            key,
            algorithms=[unverified_header.get("alg", "ES256")],
            audience="authenticated",
            issuer=SUPABASE_ISSUER,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {e}")

    return claims


# Mode invite (demo sans compte) : active par SKYN_ALLOW_GUEST=1.
# Le frontend envoie "Bearer skyn-guest" ; aucune donnee reelle n'est exposee.
ALLOW_GUEST = os.environ.get("SKYN_ALLOW_GUEST", "") == "1"
GUEST_USER = User(user_id="guest", email="invite@skyn.demo", name="Invite")


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    if ALLOW_GUEST and token == "skyn-guest":
        return GUEST_USER
    claims = await verify_supabase_jwt(token)

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
    if user_doc:
        return User(**user_doc)

    email = claims.get("email", "")
    metadata = claims.get("user_metadata", {}) or {}
    name = metadata.get("full_name") or metadata.get("name") or (email.split("@")[0] if email else "User")
    picture = metadata.get("avatar_url") or metadata.get("picture")
    user = User(user_id=user_id, email=email, name=name, picture=picture)
    await db.users.insert_one(user.model_dump())
    return user


def fallback_recommendations(scores: dict, profile: Profile) -> List[str]:
    """Deterministic, varied French recommendations when GPT-4o is unavailable."""
    ranked = sorted(
        [
            ("radiance", scores["radiance"], "Sérum vitamine C — application matinale pour réveiller un éclat plus uniforme."),
            ("imperfections", scores["imperfections"], "Niacinamide 10% en soin du soir — régule les pores et apaise les irrégularités."),
            ("texture", scores["texture"], "Exfoliation chimique douce (AHA/BHA) deux fois par semaine pour affiner le grain."),
        ],
        key=lambda x: x[1],
    )
    return [ranked[0][2], ranked[1][2], "SPF 50 quotidien — barrière non-négociable contre le photovieillissement."]


# ============ Routes ============
@api_router.get("/")
async def root():
    return {"name": "SKYN API", "status": "ok"}


@api_router.get("/auth/me", response_model=User)
async def auth_me(authorization: Optional[str] = Header(None)):
    return await get_current_user(authorization)


@api_router.get("/profile", response_model=Profile)
async def get_profile(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    doc = await db.profiles.find_one({"user_id": user.user_id}, {"_id": 0})
    if not doc:
        return Profile(user_id=user.user_id)
    return Profile(**doc)


@api_router.put("/profile", response_model=Profile)
async def update_profile(payload: ProfileUpdate, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    existing = await db.profiles.find_one({"user_id": user.user_id}, {"_id": 0}) or {"user_id": user.user_id}
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    existing.update(update_data)
    existing["user_id"] = user.user_id
    existing["updated_at"] = datetime.now(timezone.utc)
    await db.profiles.update_one(
        {"user_id": user.user_id},
        {"$set": existing},
        upsert=True,
    )
    return Profile(**existing)


@api_router.post("/reports", response_model=Report)
async def create_report(payload: ReportCreate, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    report = Report(user_id=user.user_id, **payload.model_dump())
    await db.reports.insert_one(report.model_dump())
    return report


@api_router.get("/reports", response_model=List[Report])
async def list_reports(authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    cursor = db.reports.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).limit(100)
    docs = await cursor.to_list(length=100)
    return [Report(**d) for d in docs]


@api_router.get("/reports/{report_id}", response_model=Report)
async def get_report(report_id: str, authorization: Optional[str] = Header(None)):
    user = await get_current_user(authorization)
    doc = await db.reports.find_one({"id": report_id, "user_id": user.user_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Report not found")
    return Report(**doc)


@api_router.post("/analyze", response_model=AnalyzeResponse)
async def skyn_engine_analyze(payload: AnalyzeRequest, authorization: Optional[str] = Header(None)):
    """SKYN Engine v1 — full local pipeline:
    1. MediaPipe Face Mesh preprocessing
    2. Classical CV (Sobel/Laplacian + LAB) → texture / radiance / imperfections
    3. Blob detection → spot coordinates (normalised to face bbox)
    4. Deterministic expert system → diagnosis + 3 templated recommendations
    No LLM call. The photo is processed in-memory and discarded immediately.
    """
    user = await get_current_user(authorization)

    if len(payload.image_base64) > MAX_IMAGE_B64_LEN:
        raise HTTPException(status_code=413, detail="Image too large")

    profile_doc = await db.profiles.find_one({"user_id": user.user_id}, {"_id": 0}) or {}

    from skyn_engine import analyze_skin
    try:
        out = analyze_skin(payload.image_base64, profile_doc)
    except Exception as e:
        logger.warning(f"SKYN Engine failure, returning safe defaults: {e}")
        return AnalyzeResponse(
            detected=False, low_light=False, luminance=0.0,
            global_score=70, texture=72, radiance=68, imperfections=70,
            diagnosis="Équilibre cutané préservé",
            recommendations=[
                "Maintenez une protection solaire SPF 50 quotidienne pour préserver la barrière cutanée.",
                "Hydratez matin et soir avec un sérum à l'acide hyaluronique pour soutenir l'éclat.",
                "Affinez progressivement le grain de peau avec une exfoliation douce hebdomadaire.",
            ],
            detections=[],
            source="skyn_engine_v1_fallback",
        )

    return AnalyzeResponse(
        detected=out.detected,
        low_light=out.low_light,
        luminance=out.luminance,
        global_score=out.global_score,
        texture=out.texture,
        radiance=out.radiance,
        imperfections=out.imperfections,
        diagnosis=out.diagnosis,
        recommendations=out.recommendations,
        detections=[Detection(**d) for d in out.detections],
        source=out.source,
    )


class AnalyzeV2Request(BaseModel):
    image_base64: str
    # Angles complementaires facultatifs (profil gauche, profil droit). Les vues
    # laterales exposent des zones que la vue de face aplatit.
    extra_images: List[str] = []


@api_router.post("/analyze/v2")
async def skyn_engine_analyze_v2(payload: AnalyzeV2Request,
                                 authorization: Optional[str] = Header(None)):
    """SKYN Engine v2 — analyse multi-zones et routine personnalisee.

    Differences avec /analyze (v1) :
      * 13 zones faciales au lieu d'un masque unique, sourcils/levres/pilosite
        exclus du calcul ;
      * type de peau mesure par differentiel zone T / zone U, et phototype
        estime par angle typologique individuel ;
      * lesions comptees sans plafond et classees (comedon, papule, pustule,
        marque rouge, marque brune) ;
      * routine matin/soir construite par correspondance sur le vecteur de
        preoccupations mesure, avec controle des incompatibilites d'actifs et
        introduction progressive.

    La photo est traitee en memoire et n'est jamais ecrite sur disque.
    """
    user = await get_current_user(authorization)

    images = [payload.image_base64] + list(payload.extra_images or [])
    if any(len(i) > MAX_IMAGE_B64_LEN for i in images):
        raise HTTPException(status_code=413, detail="Image too large")
    if len(images) > 3:
        raise HTTPException(status_code=400, detail="Three images maximum")

    profile_doc = await db.profiles.find_one({"user_id": user.user_id}, {"_id": 0}) or {}

    from skyn_engine.v2.pipeline import analyze_face, analyze_multi

    def _run():
        if len(images) > 1:
            return analyze_multi(images, profile_doc)
        return analyze_face(images[0], profile_doc)

    try:
        # Le pipeline est bloquant et gourmand en CPU : l'executer directement
        # dans la coroutine figerait la boucle evenementielle pour toutes les
        # autres requetes pendant plusieurs secondes.
        out = await run_in_threadpool(_run)
    except Exception as e:
        logger.exception(f"SKYN Engine v2 failure: {e}")
        raise HTTPException(status_code=500, detail="Analysis failed")

    return out.to_dict()


class AnalyzeGuidedRequest(BaseModel):
    images_base64: List[str]
    min_vues_utiles: int = 5
    cible_vues: int = 7
    max_vues: int = 9


@api_router.post("/analyze/guided")
async def skyn_engine_analyze_guided(payload: AnalyzeGuidedRequest,
                                     authorization: Optional[str] = Header(None)):
    """SKYN Engine — scan multi-vue guide (v0, prototype, pas encore relie
    a l'app mobile).

    Prend une sequence de frames (jusqu'a `max_vues` utilisables), applique
    a chaque vue la detection/classification de production INCHANGEE, puis
    suit/nettoie/confirme les observations a travers les vues — voir
    `skyn_engine.v2.multiview`, ou chaque mecanisme (tracking, nettoyage
    par observation, purete de piste, vote-gate, arret adaptatif) a ete
    valide separement dans backend/tools/. S'arrete des que la mesure est
    jugee suffisamment stable (au plus tot a `cible_vues`, au plus tard a
    `max_vues`) plutot que de toujours consommer toutes les frames
    fournies.

    N'affecte pas /analyze/v2 — endpoint additif pour un prototype de
    capture guidee.
    """
    user = await get_current_user(authorization)

    images = list(payload.images_base64 or [])
    if not images:
        raise HTTPException(status_code=400, detail="At least one image required")
    if any(len(i) > MAX_IMAGE_B64_LEN for i in images):
        raise HTTPException(status_code=413, detail="Image too large")
    if len(images) > 24:
        raise HTTPException(status_code=400, detail="Too many frames")
    if not (1 <= payload.min_vues_utiles <= payload.cible_vues <= payload.max_vues <= 24):
        raise HTTPException(status_code=400, detail="Invalid scan configuration")

    from skyn_engine.v2.multiview import orchestrer_scan, ScanConfig

    config = ScanConfig(min_vues_utiles=payload.min_vues_utiles,
                        cible_vues=payload.cible_vues, max_vues=payload.max_vues)

    def _run():
        return orchestrer_scan(images, config)

    try:
        # Meme raison que /analyze/v2 : pipeline bloquant/CPU-bound, a ne
        # jamais executer directement dans la coroutine.
        out = await run_in_threadpool(_run)
    except Exception as e:
        logger.exception(f"SKYN Engine guided scan failure: {e}")
        raise HTTPException(status_code=500, detail="Analysis failed")

    return {
        "lesions": out.lesions_confirmees,
        "frames_received": out.n_vues_recues,
        "usable_views": out.n_vues_utilisables,
        "stop_reason": out.raison_arret,
        # Statut simplifie pour piloter le frontend (TARGET_REACHED /
        # MAX_REACHED / NEED_MORE_VIEWS). CAPTURE_TOO_SIMILAR et
        # CAPTURE_LOW_QUALITY n'existent pas encore cote serveur — aucune
        # verification de diversite de pose entre vues n'est faite pour
        # l'instant, voir `view_diagnostics` ci-dessous et le commentaire
        # dans skyn_engine.v2.multiview.
        "status": out.statut,
        # Pose (yaw_proxy, roll_deg) de chaque vue retenue, dans l'ordre —
        # deja calculee par le moteur, exposee pour verifier que les vues
        # utilisables sont des poses reellement differentes plutot que des
        # quasi-doublons. Rien ne filtre encore la-dessus.
        "view_diagnostics": out.vues_diagnostics,
    }


@api_router.post("/scans")
async def ingest_scan(payload: skin_memory.ScanIngestRequest,
                       authorization: Optional[str] = Header(None)):
    """Persiste un scan deja calcule par /analyze/v2 ou /analyze/guided dans
    la memoire longitudinale (chantier 4) : rattache a la Phase active, ou
    en cree une nouvelle (baseline) s'il n'y en a aucune. Ne relance jamais
    le moteur — le client envoie la sortie qu'il a deja recue."""
    user = await get_current_user(authorization)
    try:
        scan = await skin_memory.ingest_scan(db, user.user_id, payload.source, payload.analysis)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return scan.model_dump()


@api_router.get("/periods/active")
async def get_active_period(authorization: Optional[str] = Header(None)):
    """La Phase en cours : son etat (baseline/tracking/understanding), ses
    scans, sa routine et les changements deja mesurables avec confiance
    suffisante. `null` si l'utilisateur n'a encore fait aucun scan."""
    user = await get_current_user(authorization)
    view = await skin_memory.get_active_period_view(db, user.user_id)
    return view


@api_router.get("/periods")
async def get_periods(authorization: Optional[str] = Header(None)):
    """Historique des Phases (cloturees et active), les plus recentes
    d'abord — sert a regrouper l'historique par Phase plutot qu'a plat."""
    user = await get_current_user(authorization)
    return await skin_memory.list_periods(db, user.user_id)


@api_router.post("/routine-events")
async def create_routine_event(payload: skin_memory.RoutineEventRequest,
                                authorization: Optional[str] = Header(None)):
    """Journalise un changement de routine. Un type structurant
    (step_added/step_removed/step_changed) cloture la Phase active et en
    ouvre une nouvelle : voir skin_memory.log_routine_event. A appeler
    AVANT tout /product-events accompagnant le meme changement, pour que
    l'evenement produit se rattache a la Phase fraichement ouverte."""
    user = await get_current_user(authorization)
    try:
        event = await skin_memory.log_routine_event(db, user.user_id, payload.type, payload.diff)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event.model_dump()


@api_router.post("/product-events")
async def create_product_event(payload: skin_memory.ProductEventRequest,
                                authorization: Optional[str] = Header(None)):
    """Horodate l'introduction ou l'arret d'un produit — passif, aucune
    saisie recurrente demandee a l'utilisateur au-dela de ce seul evenement."""
    user = await get_current_user(authorization)
    try:
        event = await skin_memory.log_product_event(
            db, user.user_id, payload.type, payload.product_id, payload.moment
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return event.model_dump()


@api_router.post("/recommendations", response_model=RecommendationsResponse)
async def gpt4o_recommendations(payload: RecommendationsRequest, authorization: Optional[str] = Header(None)):
    """Hybrid: numeric scores stay deterministic (frontend mock). Only the 3 final
    textual recommendations are generated by GPT-4o Vision conditioned on the
    photo + profile + scores. Falls back gracefully if the LLM call fails."""
    user = await get_current_user(authorization)
    profile_doc = await db.profiles.find_one({"user_id": user.user_id}, {"_id": 0}) or {"user_id": user.user_id}
    profile = Profile(**profile_doc)

    scores = {
        "global": payload.global_score,
        "texture": payload.texture,
        "radiance": payload.radiance,
        "imperfections": payload.imperfections,
    }

    if not EMERGENT_LLM_KEY:
        return RecommendationsResponse(
            recommendations=fallback_recommendations(scores, profile),
            source="fallback",
        )

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"skyn_{user.user_id}_{uuid.uuid4().hex[:6]}",
            system_message=(
                "Tu es un dermo-conseiller éditorial pour une application de luxe nommée SKYN. "
                "Ton style est sobre, clinique, premium, en français. "
                "Tu réponds UNIQUEMENT par un JSON strict, sans markdown, au format: "
                '{"recommendations":["…","…","…"]}. '
                "Chaque recommandation: une phrase complète, 18-26 mots, ton expert, "
                "actionnable, jamais alarmiste, sans emoji, sans guillemets internes."
            ),
        ).with_model("openai", "gpt-4o")

        # Clean base64: remove data: prefix if present
        b64 = payload.image_base64
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        # Defensive: cap size at ~3MB of base64 to keep latency reasonable
        b64 = b64[:4_500_000]

        prompt_text = (
            f"Profil utilisatrice: tranche d'âge {profile.age_range or 'inconnue'}, "
            f"environnement {profile.environment or 'inconnu'}, "
            f"priorité {profile.priority or 'inconnue'}.\n"
            f"Scores du bilan (sur 100): global {scores['global']}, "
            f"texture {scores['texture']}, éclat {scores['radiance']}, "
            f"imperfections {scores['imperfections']}.\n"
            "Analyse la photo du visage et produis EXACTEMENT 3 recommandations textuelles "
            "uniques, personnalisées et complémentaires (routine matin/soir et geste "
            "fondamental). Réponds uniquement avec le JSON demandé."
        )

        image = ImageContent(image_base64=b64)
        msg = UserMessage(text=prompt_text, file_contents=[image])

        raw = await chat.send_message(msg)
        text = raw if isinstance(raw, str) else str(raw)

        # Extract JSON
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("No JSON in LLM response")
        parsed = json.loads(m.group(0))
        recs = parsed.get("recommendations", [])
        # Sanity: must be a list of 3 non-empty strings
        recs = [str(r).strip() for r in recs if isinstance(r, str) and r.strip()]
        if len(recs) < 3:
            raise ValueError("LLM returned fewer than 3 recommendations")
        recs = recs[:3]
        return RecommendationsResponse(recommendations=recs, source="gpt-4o")
    except Exception as e:
        logger.warning(f"GPT-4o recommendations failed, using fallback: {e}")
        return RecommendationsResponse(
            recommendations=fallback_recommendations(scores, profile),
            source="fallback",
        )


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS or ["http://localhost:8081", "http://localhost:19006"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Service de l'application web (deploiement mono-hote) ----
# Construite par `npx expo export --platform web`, puis SKYN_WEB_DIR pointe sur
# le dossier dist. Les routes d'API restent sous /api : le montage a la racine
# vient APRES include_router, donc il ne peut pas les masquer.
WEB_DIR = Path(os.environ.get("SKYN_WEB_DIR", ROOT_DIR / "webapp"))
if WEB_DIR.is_dir():
    import mimetypes

    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # Le conteneur de deploiement n'embarque pas /etc/mime.types : sans ces
    # enregistrements, les polices partent en "text/plain". Chromium les
    # accepte quand meme, mais Safari est nettement plus strict sur le type
    # MIME d'une @font-face — et c'est un telephone qui ouvre cette app.
    for _ext, _type in (
        (".ttf", "font/ttf"),
        (".otf", "font/otf"),
        (".woff", "font/woff"),
        (".woff2", "font/woff2"),
    ):
        mimetypes.add_type(_type, _ext)

    class SPAStaticFiles(StaticFiles):
        """Fichiers statiques avec repli SPA.

        Une ROUTE inconnue sert index.html, pour que les liens profonds
        d'expo-router (/scan-result, /routine) survivent a un rechargement.
        Un ASSET manquant reste en 404 : renvoyer index.html a la place
        masquerait l'erreur derriere une page blanche impossible a diagnostiquer.
        On distingue les deux par la presence d'une extension.
        """

        async def get_response(self, path: str, scope):
            try:
                resp = await super().get_response(path, scope)
            except StarletteHTTPException as e:
                if e.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                    resp = await super().get_response("index.html", scope)
                    resp.headers["Cache-Control"] = "no-cache"
                    return resp
                raise
            # Les bundles portent un hash dans leur nom : immuables un an.
            # Tout le reste doit etre revalide, sinon une mise a jour ne
            # parvient jamais a un telephone qui a deja ouvert l'app.
            if "/_expo/static/" in path or path.startswith("_expo/static/"):
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                resp.headers["Cache-Control"] = "no-cache"
            return resp

    app.mount("/", SPAStaticFiles(directory=str(WEB_DIR), html=True), name="webapp")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_indexes():
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.reports.create_index([("user_id", 1), ("created_at", -1)])
        await db.profiles.create_index("user_id", unique=True)
        # Memoire persistante (chantier 4) — voir skin_memory.py.
        await db.scans.create_index([("user_id", 1), ("period_id", 1), ("created_at", 1)])
        await db.periods.create_index([("user_id", 1), ("ends_at", 1), ("starts_at", -1)])
        await db.routine_events.create_index([("period_id", 1), ("at", 1)])
        await db.product_events.create_index([("period_id", 1), ("at", 1)])
        logger.info("MongoDB indexes ensured.")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
