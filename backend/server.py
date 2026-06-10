from fastapi import FastAPI, APIRouter, Header, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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


async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_indexes():
    try:
        await db.users.create_index("email", unique=True)
        await db.users.create_index("user_id", unique=True)
        await db.reports.create_index([("user_id", 1), ("created_at", -1)])
        await db.profiles.create_index("user_id", unique=True)
        logger.info("MongoDB indexes ensured.")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
