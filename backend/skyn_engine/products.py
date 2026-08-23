"""SKYN Product Recommendation Engine.

Deterministic matching between the CV analysis metrics + user profile and a
curated catalogue of real dermo-cosmetic products. No LLM.

Every product carries a verified image URL and a product-sheet link so the
frontend can render visual, actionable cards.

Public API: recommend_products(metrics, profile_dict) -> List[dict]
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from . import actives as _actives

# Routine steps, in application order. contour_yeux is optional (added only
# when the aging concern justifies it — see recommend_products).
STEP_ORDER = ["nettoyant", "serum", "traitement", "hydratant", "protection", "contour_yeux"]

STEP_LABELS = {
    "nettoyant": "Nettoyant",
    "serum": "Sérum",
    "traitement": "Traitement ciblé",
    "hydratant": "Hydratant",
    "protection": "Protection solaire",
    "contour_yeux": "Contour des yeux",
}

# Concern keys used for matching:
#   hydration, radiance, texture, imperfections, redness, aging
CATALOG: List[dict] = [
    {
        "id": "cerave-foaming-cleanser",
        "moment": "matin_soir",
        "name": "Gel Moussant Nettoyant",
        "brand": "CeraVe",
        "step": "nettoyant",
        "key_ingredients": ["Niacinamide", "Céramides", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"imperfections": 2, "texture": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/4654864c-3a67-4c0d-9532-d8ddf2b73506/products/cerave-foaming-cleanser/cerave-foaming-cleanser_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/cerave-foaming-cleanser",
    },
    {
        "id": "cerave-hydrating-cleanser",
        "moment": "matin_soir",
        "name": "Crème Lavante Hydratante",
        "brand": "CeraVe",
        "step": "nettoyant",
        "key_ingredients": ["Céramides", "Acide hyaluronique", "Glycérine"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"hydration": 2, "redness": 1},
        "price_eur": 11.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/a1e8e76d-5c46-40b3-bced-ba17000e61f8/products/cerave-hydrating-cleanser/cerave-hydrating-cleanser_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/cerave-hydrating-cleanser",
    },
    {
        "id": "to-niacinamide",
        "moment": "soir",
        "name": "Niacinamide 10% + Zinc 1%",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Niacinamide 10%", "Zinc PCA 1%"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "redness": 1, "texture": 1},
        "price_eur": 6.5,
        "image_url": "https://incidecoder-content.storage.googleapis.com/29182f8e-b92d-428c-a108-ffc41307c408/products/the-ordinary-niacinamide-2/the-ordinary-niacinamide-2_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-niacinamide-10-zinc-1",
    },
    {
        "id": "to-hyaluronic",
        "moment": "matin_soir",
        "name": "Hyaluronic Acid 2% + B5",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Acide hyaluronique 2%", "Panthénol (B5)"],
        "skin_types": ["Normale", "Mixte", "Grasse", "Sèche"],
        "concerns": {"hydration": 3, "radiance": 1},
        "price_eur": 8.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9ad01f1a-9e1b-4f1d-ad5c-1b7a95d236ea/products/the-ordinary-hyaluronic-acid-2-b5/the-ordinary-hyaluronic-acid-2-b5_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-hyaluronic-acid-2-b5",
    },
    {
        "id": "lrp-vitamin-c10",
        "moment": "matin",
        "name": "Pure Vitamin C10 Sérum",
        "brand": "La Roche-Posay",
        "step": "serum",
        "key_ingredients": ["Vitamine C pure 10%", "Acide salicylique", "Néurosensine"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"radiance": 3, "aging": 1, "texture": 1},
        "price_eur": 40.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/b45aa88f-e27e-48de-a1c0-56ac20447057/products/la-roche-posay-pure-vitamin-c10/la-roche-posay-pure-vitamin-c10_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-pure-vitamin-c10",
    },
    {
        "id": "vichy-mineral-89",
        "moment": "matin_soir",
        "name": "Minéral 89 Booster Quotidien",
        "brand": "Vichy",
        "step": "serum",
        "key_ingredients": ["Eau volcanique 89%", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Grasse", "Sèche"],
        "concerns": {"hydration": 3, "radiance": 1},
        "price_eur": 25.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/148060a4-8628-4007-b026-c98dbafb0334/products/vichy-mineral-89/vichy-mineral-89_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/vichy-mineral-89",
    },
    {
        "id": "lrp-retinol-b3",
        "moment": "soir",
        "name": "Retinol B3 Sérum",
        "brand": "La Roche-Posay",
        "step": "serum",
        "key_ingredients": ["Rétinol 0,3%", "Vitamine B3"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"aging": 3, "texture": 2},
        "price_eur": 40.0,
        "min_age": "25-40",  # jamais recommandé aux <25
        "avoid_if_reactive": True,
        "image_url": "https://incidecoder-content.storage.googleapis.com/6289f044-3cec-4691-935c-c277d841fd00/products/la-roche-posay-retinol-serum/la-roche-posay-retinol-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-retinol-serum",
    },
    {
        "id": "to-glycolic-toner",
        "moment": "soir",
        "name": "Glycolic Acid 7% Toning Solution",
        "brand": "The Ordinary",
        "step": "traitement",
        "key_ingredients": ["Acide glycolique 7% (AHA)", "Aloe vera", "Ginseng"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"texture": 3, "radiance": 2},
        "min_age": None,
        "avoid_if_reactive": True,
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/0b644d11-d3dd-4bc3-a8ac-ae7ed0b5e58a/products/the-ordinary-glycolic-acid-7-toning-solution/the-ordinary-glycolic-acid-7-toning-solution_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-glycolic-acid-7-toning-solution",
    },
    {
        "id": "pc-bha-2",
        "moment": "soir",
        "name": "Skin Perfecting 2% BHA Liquid Exfoliant",
        "brand": "Paula's Choice",
        "step": "traitement",
        "key_ingredients": ["Acide salicylique 2% (BHA)", "Thé vert"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "texture": 2},
        "avoid_if_reactive": True,
        "price_eur": 36.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/46dc7618-6dbb-4379-a069-aa9f4535742e/products/paulas-choice-skin-perfecting-2-bha-liquid-exfoliant/paulas-choice-skin-perfecting-2-bha-liquid-exfoliant_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/paulas-choice-skin-perfecting-2-bha-liquid-exfoliant",
    },
    {
        "id": "lrp-effaclar-duo",
        "moment": "soir",
        "name": "Effaclar Duo+ M",
        "brand": "La Roche-Posay",
        "step": "traitement",
        "key_ingredients": ["Niacinamide", "Acide salicylique", "Zinc"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "texture": 1},
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/31c4a09f-1c76-41c0-a725-b88bddd8e856/products/la-roche-posay-effaclar-duo-2/la-roche-posay-effaclar-duo-2_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-effaclar-duo",
    },
    {
        "id": "avene-comedomed",
        "moment": "matin_soir",
        "name": "Cleanance Comedomed Concentré",
        "brand": "Avène",
        "step": "traitement",
        "key_ingredients": ["Comedoclastin (cardère)", "Eau thermale d'Avène"],
        "skin_types": ["Grasse"],
        "concerns": {"imperfections": 3},
        "price_eur": 16.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/18dbc6f6-d3f6-46b0-adf1-142b02bac41b/products/avene-cleanance-comedomed/avene-cleanance-comedomed_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/avene-cleanance-comedomed",
    },
    {
        "id": "lrp-cicaplast-b5",
        "moment": "matin_soir",
        "name": "Cicaplast Baume B5+",
        "brand": "La Roche-Posay",
        "step": "traitement",
        "key_ingredients": ["Panthénol 5%", "Madécassoside", "Zinc-cuivre-manganèse"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"redness": 3, "hydration": 2},
        "price_eur": 11.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/fa651e74-71b9-49bf-a0f4-470b2a7894d1/products/la-roche-posay-cicaplast-baume-b5/la-roche-posay-cicaplast-baume-b5_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-cicaplast-baume-b5",
    },
    {
        "id": "avene-cicalfate",
        "moment": "matin_soir",
        "name": "Cicalfate+ Crème Réparatrice",
        "brand": "Avène",
        "step": "traitement",
        "key_ingredients": ["C+-Restore", "Sucralfate", "Eau thermale d'Avène"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"redness": 3, "hydration": 1},
        "price_eur": 10.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/f258dae9-3e29-457e-9e26-9887392b5aa5/products/cicalfate-repairing-protective-cream-/cicalfate-repairing-protective-cream-_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/avene-cicalfate-repairing-protective-cream",
    },
    {
        "id": "cerave-facial-lotion",
        "moment": "matin_soir",
        "name": "Lotion Hydratante Visage",
        "brand": "CeraVe",
        "step": "hydratant",
        "key_ingredients": ["Céramides", "Niacinamide", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Grasse", "Sèche"],
        "concerns": {"hydration": 2, "redness": 1},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/d0f20a4c-27a4-4ffb-a65e-f93fe5a8ab57/products/cerave-facial-moisturising-lotion/cerave-facial-moisturising-lotion_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/cerave-facial-moisturising-lotion",
    },
    {
        "id": "lrp-anthelios-uvmune",
        "moment": "matin",
        "name": "Anthelios UVMune 400 Fluide Invisible SPF50+",
        "brand": "La Roche-Posay",
        "step": "protection",
        "key_ingredients": ["Mexoryl 400", "Filtres UVB/UVA large spectre"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"aging": 2, "radiance": 1, "imperfections": 1},
        "price_eur": 20.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/bbf408ac-123f-45b7-bbea-398090ab5f2f/products/la-roche-posay-anthelio-uvmune-400-invisible-fluid-spf50/la-roche-posay-anthelio-uvmune-400-invisible-fluid-spf50_front_photo_300x300@2x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-anthelios-uvmune-400-invisible-fluid-spf50",
    },
    {
        "id": 'lrp-effaclar-gel',
        "moment": 'matin_soir',
        "name": 'Effaclar Gel Moussant Purifiant',
        "brand": 'La Roche-Posay',
        "step": 'nettoyant',
        "key_ingredients": ['Zinc pidolate', 'Eau thermale'],
        "skin_types": ['Mixte', 'Grasse'],
        "concerns": {'imperfections': 2, 'texture': 1},
        "price_eur": 13.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/551abc1e-acba-4853-8100-279848b0f19c/products/la-roche-posay-effaclar-purifying-foaming-gel/la-roche-posay-effaclar-purifying-foaming-gel_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/la-roche-posay-effaclar-purifying-foaming-gel',
    },
    {
        "id": 'lrp-toleriane-cleanser',
        "moment": 'matin_soir',
        "name": 'Toleriane Gel Nettoyant Apaisant',
        "brand": 'La Roche-Posay',
        "step": 'nettoyant',
        "key_ingredients": ['Niacinamide', 'Céramides', 'Prébiotiques'],
        "skin_types": ['Normale', 'Sèche'],
        "concerns": {'redness': 2, 'hydration': 1},
        "price_eur": 15.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/593227fd-9495-43da-bf4c-0f6e76e2855a/products/la-roche-posay-toleriane-hydrating-gentle-cleanser/la-roche-posay-toleriane-hydrating-gentle-cleanser_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/la-roche-posay-toleriane-hydrating-gentle-cleanser',
    },
    {
        "id": 'cerave-sa-cleanser',
        "moment": 'matin_soir',
        "name": 'SA Gel Nettoyant Anti-Rugosités',
        "brand": 'CeraVe',
        "step": 'nettoyant',
        "key_ingredients": ['Acide salicylique', 'Céramides'],
        "skin_types": ['Mixte', 'Grasse'],
        "concerns": {'texture': 2, 'imperfections': 1},
        "price_eur": 13.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/48091d69-2d2b-4fd1-bdef-8525fa21eed7/products/cerave-sa-smoothing-cleanser/cerave-sa-smoothing-cleanser_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/cerave-sa-smoothing-cleanser',
    },
    {
        "id": 'to-azelaic',
        "moment": 'soir',
        "name": 'Azelaic Acid Suspension 10%',
        "brand": 'The Ordinary',
        "step": 'serum',
        "key_ingredients": ['Acide azélaïque 10%'],
        "skin_types": ['Normale', 'Mixte', 'Grasse'],
        "concerns": {'redness': 2, 'imperfections': 2, 'radiance': 1},
        "price_eur": 9.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/05329251-c6ce-4ecc-8736-1ce3e5e7f96a/products/the-ordinary-azelaic-acid-suspension-10/the-ordinary-azelaic-acid-suspension-10_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/the-ordinary-azelaic-acid-suspension-10',
    },
    {
        "id": 'to-alpha-arbutin',
        "moment": 'matin_soir',
        "name": 'Alpha Arbutin 2% + HA',
        "brand": 'The Ordinary',
        "step": 'serum',
        "key_ingredients": ['Alpha-arbutine 2%', 'Acide hyaluronique'],
        "skin_types": ['Normale', 'Mixte', 'Grasse', 'Sèche'],
        "concerns": {'radiance': 2, 'aging': 1},
        "price_eur": 10.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/75ff4cd0-b6dc-4ab2-ba9a-5211dbf35e6d/products/the-ordinary-alpha-arbutin-2-ha/the-ordinary-alpha-arbutin-2-ha_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/the-ordinary-alpha-arbutin-2-ha',
    },
    {
        "id": 'lrp-hyalu-b5',
        "moment": 'matin_soir',
        "name": 'Hyalu B5 Sérum',
        "brand": 'La Roche-Posay',
        "step": 'serum',
        "key_ingredients": ['Acide hyaluronique pur', 'Vitamine B5', 'Madécassoside'],
        "skin_types": ['Normale', 'Sèche'],
        "concerns": {'hydration': 2, 'aging': 2},
        "price_eur": 40.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/ec7c83cd-8867-4116-81d5-a82da03e582e/products/la-roche-posay-hyalu-b5-serum/la-roche-posay-hyalu-b5-serum_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/la-roche-posay-hyalu-b5-serum',
    },
    {
        "id": 'cerave-retinol-serum',
        "moment": 'soir',
        "name": 'Sérum Anti-Marques Rétinol',
        "brand": 'CeraVe',
        "step": 'serum',
        "key_ingredients": ['Rétinol encapsulé', 'Niacinamide', 'Céramides'],
        "skin_types": ['Normale', 'Mixte', 'Grasse'],
        "concerns": {'imperfections': 2, 'texture': 2, 'aging': 1},
        "min_age": '25-40',
        "avoid_if_reactive": True,
        "price_eur": 20.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/5eaab1a4-6021-42c6-a109-c73b7546495f/products/cerave-resurfacing-retinol-serum/cerave-resurfacing-retinol-serum_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/cerave-resurfacing-retinol-serum',
    },
    {
        "id": 'to-lactic-5',
        "moment": 'soir',
        "name": 'Lactic Acid 5% + HA',
        "brand": 'The Ordinary',
        "step": 'traitement',
        "key_ingredients": ['Acide lactique 5%', 'Acide hyaluronique', 'Tasmannia'],
        "skin_types": ['Normale', 'Sèche', 'Mixte'],
        "concerns": {'texture': 3, 'radiance': 1},
        "avoid_if_reactive": True,
        "price_eur": 8.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/b6da0449-91b1-4047-90bc-7eb374e937a4/products/ordinary-lactic-acid-5-ha/ordinary-lactic-acid-5-ha_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/the-ordinary-lactic-acid-5-ha-3',
    },
    {
        "id": 'lrp-effaclar-mat',
        "moment": 'matin_soir',
        "name": 'Effaclar Mat Hydratant Sébo-Régulateur',
        "brand": 'La Roche-Posay',
        "step": 'hydratant',
        "key_ingredients": ['Sebulyse', 'Microexfoliants', 'Eau thermale'],
        "skin_types": ['Mixte', 'Grasse'],
        "concerns": {'imperfections': 2, 'texture': 1},
        "price_eur": 16.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/8ec453d6-82a2-4b73-9687-6b7194b61af1/products/la-roche-posay-effaclar-mat/la-roche-posay-effaclar-mat_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/la-roche-posay-effaclar-mat',
    },
    {
        "id": 'neutrogena-hydro-boost',
        "moment": 'matin_soir',
        "name": 'Hydro Boost Gel-Crème',
        "brand": 'Neutrogena',
        "step": 'hydratant',
        "key_ingredients": ['Acide hyaluronique', 'Tréhalose'],
        "skin_types": ['Normale', 'Mixte', 'Grasse'],
        "concerns": {'hydration': 2, 'radiance': 1},
        "price_eur": 12.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/a76d235a-b5a3-4203-978f-51c47e550744/products/neutrogena-hydro-boost-water-gel/neutrogena-hydro-boost-water-gel_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/neutrogena-hydro-boost-water-gel',
    },
    {
        "id": 'cerave-moisturising-cream',
        "moment": 'matin_soir',
        "name": 'Crème Hydratante Riche',
        "brand": 'CeraVe',
        "step": 'hydratant',
        "key_ingredients": ['Céramides', 'Acide hyaluronique', 'Technologie MVE'],
        "skin_types": ['Sèche'],
        "concerns": {'hydration': 3, 'redness': 1},
        "price_eur": 12.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/9945d0b5-7d9d-47a5-af2b-967b65bb1600/products/cerave-moisturising-cream/cerave-moisturising-cream_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/cerave-moisturising-cream',
    },
    {
        "id": 'avene-tolerance-control',
        "moment": 'matin_soir',
        "name": 'Tolérance Control Crème Apaisante',
        "brand": 'Avène',
        "step": 'hydratant',
        "key_ingredients": ['D-Sensinose', "Eau thermale d'Avène"],
        "skin_types": ['Normale', 'Sèche'],
        "concerns": {'redness': 3, 'hydration': 2},
        "price_eur": 17.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/2f8cedb5-6956-4cf3-b651-c2a6ce620c20/products/avene-tolerance-control-soothing-skin-recovery-cream/avene-tolerance-control-soothing-skin-recovery-cream_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/avene-tolerance-control-soothing-skin-recovery-cream',
    },
    {
        "id": 'vichy-aqualia-rich',
        "moment": 'matin_soir',
        "name": 'Aqualia Thermal Crème Riche',
        "brand": 'Vichy',
        "step": 'hydratant',
        "key_ingredients": ['Acide hyaluronique', 'Eau volcanique'],
        "skin_types": ['Normale', 'Sèche'],
        "concerns": {'hydration': 2, 'radiance': 1},
        "price_eur": 20.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/04ad2936-4c8c-43e2-b52c-21b853e2f64f/products/vichy-aqualia-thermal-rich-cream/vichy-aqualia-thermal-rich-cream_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/vichy-aqualia-thermal-rich-cream',
    },
    {
        "id": 'avene-cleanance-spf50',
        "moment": 'matin',
        "name": 'Cleanance Solaire SPF 50+',
        "brand": 'Avène',
        "step": 'protection',
        "key_ingredients": ['Filtres très haute protection', 'Comedoclastin'],
        "skin_types": ['Mixte', 'Grasse'],
        "concerns": {'imperfections': 1, 'aging': 2},
        "price_eur": 18.0,
        "image_url": 'https://incidecoder-content.storage.googleapis.com/b38f2437-1b8d-47c5-844d-5b2e1b15638f/products/avene-very-high-protection-cleanance-spf50/avene-very-high-protection-cleanance-spf50_front_photo_300x300@1x.webp',
        "url": 'https://incidecoder.com/products/avene-very-high-protection-cleanance-spf50',
    },
    {
        "id": "bioderma-sensibio-h2o",
        "moment": "matin_soir",
        "name": "Sensibio H2O Eau Micellaire",
        "brand": "Bioderma",
        "step": "nettoyant",
        "key_ingredients": ["Sans parfum", "pH neutre"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"redness": 3, "hydration": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/f166c396-2907-49ca-bbf6-13d49a8406c7/products/bioderma-sensibio-h2o/bioderma-sensibio-h2o_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/bioderma-sensibio-h2o",
    },
    {
        "id": "bioderma-hydrabio-h2o",
        "moment": "matin_soir",
        "name": "Hydrabio H2O Eau Micellaire",
        "brand": "Bioderma",
        "step": "nettoyant",
        "key_ingredients": ["Acide gluconique", "Glycérol"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"hydration": 2, "radiance": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/6eefb6e2-d4bb-49ef-b596-ee64f7ce1807/products/bioderma-hydrabio-h2o/bioderma-hydrabio-h2o_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/bioderma-hydrabio-h2o",
    },
    {
        "id": "lrp-toleriane-dermo-cleanser",
        "moment": "matin_soir",
        "name": "Toleriane Dermo-Nettoyant",
        "brand": "La Roche-Posay",
        "step": "nettoyant",
        "key_ingredients": ["Glycérine", "Eau thermale"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 2, "redness": 1},
        "price_eur": 14.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/178a8299-2fee-4478-b2eb-499c1b2ce9da/products/la-roche-posay-toleriane-dermo-cleanser/la-roche-posay-toleriane-dermo-cleanser_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-toleriane-dermo-cleanser",
    },
    {
        "id": "cerave-sa-renewing-cleanser",
        "moment": "soir",
        "name": "Nettoyant Renouvelant SA",
        "brand": "CeraVe",
        "step": "nettoyant",
        "key_ingredients": ["Acide salicylique", "Céramides"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"texture": 2, "imperfections": 1},
        "price_eur": 14.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/1a4eb0c6-9f54-4794-b0a0-aae58a51d638/products/cerave-salicylic-acid-cleanser/cerave-salicylic-acid-cleanser_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cerave-renewing-sa-cleanser",
    },
    {
        "id": "avene-cleanance-gel",
        "moment": "matin_soir",
        "name": "Cleanance Gel Nettoyant",
        "brand": "Avène",
        "step": "nettoyant",
        "key_ingredients": ["Monolaurine", "Eau thermale"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/666841b2-1419-428a-a7ce-ec4660fa1742/products/avene-cleanance-cleansing-gel/avene-cleanance-cleansing-gel_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/avene-cleanance-cleansing-gel",
    },
    {
        "id": "simple-refreshing-wash",
        "moment": "matin_soir",
        "name": "Gel Nettoyant Rafraîchissant",
        "brand": "Simple",
        "step": "nettoyant",
        "key_ingredients": ["Sans savon", "Vitamines B5/E"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"redness": 1},
        "price_eur": 6.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/3e3ccb83-edfe-426f-abba-778f86865e28/products/simple-kind-to-skin-refreshing-facial-wash/simple-kind-to-skin-refreshing-facial-wash_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/simple-kind-to-skin-refreshing-facial-wash",
    },
    {
        "id": "cetaphil-gentle-cleanser",
        "moment": "matin_soir",
        "name": "Nettoyant Doux",
        "brand": "Cetaphil",
        "step": "nettoyant",
        "key_ingredients": ["Sans savon", "Glycérine"],
        "skin_types": ["Normale", "Sèche", "Mixte", "Grasse"],
        "concerns": {"redness": 1, "hydration": 1},
        "price_eur": 10.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/95cd5beb-698b-4b7e-a4b8-c8f2cc8b616c/products/cetaphil-gentle-skin-cleanser-4/cetaphil-gentle-skin-cleanser-4_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cetaphil-gentle-skin-cleanser",
    },
    {
        "id": "to-squalane-cleanser",
        "moment": "soir",
        "name": "Squalane Cleanser",
        "brand": "The Ordinary",
        "step": "nettoyant",
        "key_ingredients": ["Squalane végétal"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 2},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/652155ff-6b15-4939-81ec-55ae278cea9e/products/the-ordinary-squalane-cleanser/the-ordinary-squalane-cleanser_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-squalane-cleanser",
    },
    {
        "id": "neutrogena-hydroboost-cleanser",
        "moment": "matin_soir",
        "name": "Hydro Boost Gel Nettoyant",
        "brand": "Neutrogena",
        "step": "nettoyant",
        "key_ingredients": ["Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"hydration": 1},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/8a4ab5c6-d9a9-472d-840d-d00c48e987ef/products/neutrogena-hydro-boost-cleansing-gel/neutrogena-hydro-boost-cleansing-gel_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/neutrogena-hydro-boost-cleansing-gel",
    },
    {
        "id": "inkey-oat-cleansing-balm",
        "moment": "soir",
        "name": "Oat Cleansing Balm",
        "brand": "The Inkey List",
        "step": "nettoyant",
        "key_ingredients": ["Avoine", "Squalane"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 1, "redness": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/88d14c7b-ce70-4a31-a5f8-d43a95492865/products/the-inkey-list-oat-cleansing-balm/the-inkey-list-oat-cleansing-balm_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-inkey-list-oat-cleansing-balm",
    },
    {
        "id": "cosrx-low-ph-cleanser",
        "moment": "matin",
        "name": "Low pH Good Morning Gel Cleanser",
        "brand": "COSRX",
        "step": "nettoyant",
        "key_ingredients": ["Thé vert", "pH 5"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"texture": 1},
        "price_eur": 11.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/3e0a4569-7495-45fa-bdfe-ce2c408ff6e3/products/cosrx-low-ph-good-morning-gel-cleanser-5/cosrx-low-ph-good-morning-gel-cleanser-5_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cosrx-low-ph-good-morning-gel-cleanser",
    },
    {
        "id": "cosrx-salicylic-cleanser",
        "moment": "matin_soir",
        "name": "Salicylic Acid Daily Gentle Cleanser",
        "brand": "COSRX",
        "step": "nettoyant",
        "key_ingredients": ["Acide salicylique doux", "Betaine salicylate"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2, "texture": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9213d8dc-82b4-4dcd-b19b-8dba92f4479d/products/corsx-salicylic-acid-daily-gentle-cleanser-2/corsx-salicylic-acid-daily-gentle-cleanser-2_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cosrx-salicylic-acid-daily-gentle-cleanser",
    },
    {
        "id": "inkey-salicylic-cleanser",
        "moment": "soir",
        "name": "Salicylic Acid Cleanser",
        "brand": "The Inkey List",
        "step": "nettoyant",
        "key_ingredients": ["Acide salicylique 2%"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2},
        "price_eur": 11.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/c148967b-d990-4916-a0c5-36685553efe5/products/the-inkey-list-salicylic-acid-cleanser-2/the-inkey-list-salicylic-acid-cleanser-2_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-inkey-list-salicylic-acid-cleanser",
    },
    {
        "id": "to-salicylic-2",
        "moment": "soir",
        "name": "Salicylic Acid 2% Solution",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Acide salicylique 2%"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "texture": 1},
        "avoid_if_reactive": True,
        "price_eur": 7.5,
        "image_url": "https://incidecoder-content.storage.googleapis.com/4fe36288-30fc-4028-8788-cb2cfa1a85da/products/the-ordinary-salicylic-acid-2-solution/the-ordinary-salicylic-acid-2-solution_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-salicylic-acid-2-solution",
    },
    {
        "id": "to-matrixyl",
        "moment": "soir",
        "name": "Matrixyl 10% + HA",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Peptides Matrixyl", "Acide hyaluronique"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"aging": 3},
        "min_age": "25-40",
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/8c926131-2156-4342-8f85-f275f83a12ab/products/the-ordinary-matrixyl-10-ha/the-ordinary-matrixyl-10-ha_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-matrixyl-10-ha",
    },
    {
        "id": "to-buffet",
        "moment": "soir",
        "name": "Buffet Multi-Peptide Serum",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Complexe peptidique", "Acide hyaluronique"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"aging": 3, "texture": 1},
        "min_age": "25-40",
        "price_eur": 16.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/473ecee9-c181-4eaf-8c05-2b977c573993/products/the-ordinary-buffet/the-ordinary-buffet_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-buffet",
    },
    {
        "id": "to-vitc-23",
        "moment": "soir",
        "name": "Vitamin C Suspension 23% + HA Spheres 2%",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Vitamine C pure 23%"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"radiance": 3},
        "avoid_if_reactive": True,
        "price_eur": 8.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/bbf45d42-67a6-4a8d-9203-94294e343f48/products/the-ordinary-vitamin-c-suspension-23-ha-spheres-2/the-ordinary-vitamin-c-suspension-23-ha-spheres-2_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-vitamin-c-suspension-23-ha-spheres-2",
    },
    {
        "id": "to-ascorbyl-glucoside",
        "moment": "matin",
        "name": "Ascorbyl Glucoside Solution 12%",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Vitamine C douce 12%"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"radiance": 2},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/b7d50e6b-9306-4ccf-a239-17977c16e0f6/products/the-ordinary-ascorbyl-glucoside-solution-12/the-ordinary-ascorbyl-glucoside-solution-12_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-ascorbyl-glucoside-solution-12",
    },
    {
        "id": "lrp-pigmentclar-serum",
        "moment": "matin",
        "name": "Pigmentclar Sérum",
        "brand": "La Roche-Posay",
        "step": "serum",
        "key_ingredients": ["LHA", "Niacinamide"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"radiance": 2},
        "price_eur": 35.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/5b9b6daf-3b00-4618-b47f-516953a2ba9f/products/la-roche-posay-pigmentclar-serum/la-roche-posay-pigmentclar-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-pigmentclar-serum",
    },
    {
        "id": "vichy-liftactiv-vitc",
        "moment": "matin",
        "name": "LiftActiv Vitamin C Sérum",
        "brand": "Vichy",
        "step": "serum",
        "key_ingredients": ["Vitamine C 15%", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"radiance": 2, "aging": 1},
        "price_eur": 30.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/4b51adc6-f0c8-413f-8098-b3db15e5176e/products/vichy-liftactiv-vitamin-c-serum/vichy-liftactiv-vitamin-c-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/vichy-liftactiv-vitamin-c-serum",
    },
    {
        "id": "pc-niacinamide-booster",
        "moment": "soir",
        "name": "10% Niacinamide Booster",
        "brand": "Paula's Choice",
        "step": "serum",
        "key_ingredients": ["Niacinamide 10%"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3},
        "price_eur": 42.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/e9a99df8-27e9-43ed-9bc7-d474053b7b34/products/paulas-choice-10-niacinamide-booster/paulas-choice-10-niacinamide-booster_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/paulas-choice-10-niacinamide-booster",
    },
    {
        "id": "pc-c15-booster",
        "moment": "matin",
        "name": "C15 Super Booster",
        "brand": "Paula's Choice",
        "step": "serum",
        "key_ingredients": ["Vitamine C pure 15%", "Vitamine E"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"radiance": 3, "aging": 1},
        "avoid_if_reactive": True,
        "price_eur": 54.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/a11a8616-5483-4477-8ae8-4cdc7f6339d2/products/paulas-choice-c15-super-booster/paulas-choice-c15-super-booster_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/paulas-choice-c15-super-booster",
    },
    {
        "id": "pc-resist-omega",
        "moment": "soir",
        "name": "Resist Omega+ Complex Sérum",
        "brand": "Paula's Choice",
        "step": "serum",
        "key_ingredients": ["Oméga 3-6-9", "Antioxydants"],
        "skin_types": ["Sèche"],
        "concerns": {"aging": 3, "hydration": 1},
        "min_age": "40-60",
        "price_eur": 44.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/2206d554-1fc0-4917-9d48-48421a841178/products/paulas-choice-resist-omega-complex-serum/paulas-choice-resist-omega-complex-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/paulas-choice-resist-omega-complex-serum",
    },
    {
        "id": "neutrogena-wrinkle-repair",
        "moment": "soir",
        "name": "Rapid Wrinkle Repair Sérum",
        "brand": "Neutrogena",
        "step": "serum",
        "key_ingredients": ["Rétinol", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"aging": 3, "texture": 1},
        "min_age": "25-40",
        "avoid_if_reactive": True,
        "price_eur": 22.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/802308d6-bf73-43ee-ba42-b9086d04c8da/products/neutrogena-rapid-wrinkle-repair-serum/neutrogena-rapid-wrinkle-repair-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/neutrogena-rapid-wrinkle-repair-serum",
    },
    {
        "id": "olay-regenerist-serum",
        "moment": "matin_soir",
        "name": "Regenerist Micro-Sculpting Sérum",
        "brand": "Olay",
        "step": "serum",
        "key_ingredients": ["Niacinamide", "Peptides", "Acide hyaluronique"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"aging": 2, "hydration": 1},
        "min_age": "40-60",
        "price_eur": 32.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/6399b7d3-3dd8-4c5c-88a2-c7aa00862824/products/olay-regenerist-micro-sculpting-serum/olay-regenerist-micro-sculpting-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/olay-regenerist-micro-sculpting-serum",
    },
    {
        "id": "cosrx-snail-mucin",
        "moment": "soir",
        "name": "Advanced Snail 96 Mucin Power Essence",
        "brand": "COSRX",
        "step": "serum",
        "key_ingredients": ["Mucine d'escargot 96%"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"hydration": 2, "texture": 1},
        "price_eur": 18.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/ab13a2a5-0c6b-4800-9c44-eb72d5778ca8/products/cosrx-advanced-snail-96-mucin-power-essence/cosrx-advanced-snail-96-mucin-power-essence_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cosrx-advanced-snail-96-mucin-power-essence",
    },
    {
        "id": "cosrx-aha-bha-toner",
        "moment": "soir",
        "name": "AHA/BHA Clarifying Treatment Toner",
        "brand": "COSRX",
        "step": "serum",
        "key_ingredients": ["AHA", "BHA doux"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"texture": 2, "imperfections": 1},
        "avoid_if_reactive": True,
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/fbe76dc0-74ca-46eb-9fdf-c58a08fd2fdc/products/cosrx-aha-bha-clarifying-treatment-toner/cosrx-aha-bha-clarifying-treatment-toner_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cosrx-aha-bha-clarifying-treatment-toner",
    },
    {
        "id": "klairs-vitamin-drop",
        "moment": "matin",
        "name": "Freshly Juiced Vitamin Drop",
        "brand": "Klairs",
        "step": "serum",
        "key_ingredients": ["Vitamine C 5%"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"radiance": 2},
        "price_eur": 19.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/1125b27b-9dbb-4997-bbd4-201537dbd99a/products/klairs-freshly-juiced-vitamin-drop/klairs-freshly-juiced-vitamin-drop_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/klairs-freshly-juiced-vitamin-drop",
    },
    {
        "id": "inkey-niacinamide",
        "moment": "soir",
        "name": "Niacinamide Sérum",
        "brand": "The Inkey List",
        "step": "serum",
        "key_ingredients": ["Niacinamide"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/260726d8-9cc0-4337-bd10-1c8f243b7369/products/the-inkey-list-niacinamide/the-inkey-list-niacinamide_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-inkey-list-niacinamide",
    },
    {
        "id": "inkey-retinol",
        "moment": "soir",
        "name": "Retinol Sérum",
        "brand": "The Inkey List",
        "step": "serum",
        "key_ingredients": ["Rétinol"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"aging": 2, "texture": 1},
        "min_age": "25-40",
        "avoid_if_reactive": True,
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/db977b8a-43ee-462d-ad94-30e642bb881f/products/the-inkey-list-retinol/the-inkey-list-retinol_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-inkey-list-retinol",
    },
    {
        "id": "inkey-hyaluronic",
        "moment": "matin_soir",
        "name": "Hyaluronic Acid Sérum",
        "brand": "The Inkey List",
        "step": "serum",
        "key_ingredients": ["Acide hyaluronique multi-poids"],
        "skin_types": ["Normale", "Sèche", "Mixte", "Grasse"],
        "concerns": {"hydration": 2},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/cdd3981e-f8b9-416d-97b8-c10ef719203e/products/the-inkey-list-hyaluronic-acid-serum/the-inkey-list-hyaluronic-acid-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-inkey-list-hyaluronic-acid-serum",
    },
    {
        "id": "to-mandelic-acid",
        "moment": "soir",
        "name": "Mandelic Acid 10% + HA",
        "brand": "The Ordinary",
        "step": "serum",
        "key_ingredients": ["Acide mandélique 10% (AHA doux)"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"texture": 2, "radiance": 1},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9b18ebea-94eb-4d0d-83a3-4ecb415532bf/products/the-ordinary-mandelic-acid-10-ha/the-ordinary-mandelic-acid-10-ha_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-mandelic-acid-10-ha",
    },
    {
        "id": "beauty-of-joseon-glow-serum",
        "moment": "matin",
        "name": "Glow Serum Propolis + Niacinamide",
        "brand": "Beauty of Joseon",
        "step": "serum",
        "key_ingredients": ["Propolis", "Niacinamide 2%"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"radiance": 2, "hydration": 1},
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/2163bfdb-ff76-45d0-a5dc-dead45e035f1/products/beauty-of-joseon-glow-serum-propolis-niacinamide/beauty-of-joseon-glow-serum-propolis-niacinamide_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/beauty-of-joseon-glow-serum-propolis-niacinamide",
    },
    {
        "id": "anua-heartleaf-toner",
        "moment": "matin_soir",
        "name": "Heartleaf 77% Soothing Toner",
        "brand": "Anua",
        "step": "serum",
        "key_ingredients": ["Extrait de véronique 77%"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"redness": 2, "imperfections": 1},
        "price_eur": 19.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/dadf55bf-6a68-4645-beb9-cc93b6401f3d/products/anua-heartleaf-77-soothing-toner/anua-heartleaf-77-soothing-toner_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/anua-heartleaf-77-soothing-toner",
    },
    {
        "id": "skin1004-centella-ampoule",
        "moment": "matin_soir",
        "name": "Madagascar Centella Ampoule",
        "brand": "SKIN1004",
        "step": "serum",
        "key_ingredients": ["Centella asiatica 100%"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"redness": 2, "imperfections": 1},
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/a28e267d-19a2-46cf-929b-06ad42baec7f/products/skin1004-madagascar-centella-ampoule/skin1004-madagascar-centella-ampoule_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/skin1004-madagascar-centella-ampoule",
    },
    {
        "id": "innisfree-green-tea-serum",
        "moment": "matin_soir",
        "name": "Green Tea Seed Sérum",
        "brand": "Innisfree",
        "step": "serum",
        "key_ingredients": ["Thé vert de Jeju", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"hydration": 2, "radiance": 1},
        "price_eur": 24.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9af0258a-16d4-4573-be2b-ec97902b978a/products/innisfree-green-tea-seed-serum/innisfree-green-tea-seed-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/innisfree-green-tea-seed-serum",
    },
    {
        "id": "torriden-dive-in-serum",
        "moment": "matin_soir",
        "name": "Dive-In Low Molecule Hyaluronic Acid Sérum",
        "brand": "Torriden",
        "step": "serum",
        "key_ingredients": ["5 poids d'acide hyaluronique"],
        "skin_types": ["Normale", "Sèche", "Mixte", "Grasse"],
        "concerns": {"hydration": 3},
        "price_eur": 16.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/02a475b8-ee00-417e-a41d-efc65cd9d79e/products/torriden-dive-in-low-molecule-hyaluronic-acid-serum/torriden-dive-in-low-molecule-hyaluronic-acid-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/torriden-dive-in-low-molecule-hyaluronic-acid-serum",
    },
    {
        "id": "to-caffeine-solution",
        "moment": "matin",
        "name": "Caffeine Solution 5% + EGCG",
        "brand": "The Ordinary",
        "step": "contour_yeux",
        "key_ingredients": ["Caféine 5%", "EGCG (thé vert)"],
        "skin_types": ["Normale", "Mixte", "Grasse", "Sèche"],
        "concerns": {"aging": 1},
        "price_eur": 8.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/f72c7027-0115-4e9b-af12-795c8519e06d/products/the-ordinary-caffeine-solution-5-egcg/the-ordinary-caffeine-solution-5-egcg_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-caffeine-solution-5-egcg",
    },
    {
        "id": "mario-badescu-drying-lotion",
        "moment": "soir",
        "name": "Drying Lotion",
        "brand": "Mario Badescu",
        "step": "traitement",
        "key_ingredients": ["Soufre", "Acide salicylique"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3},
        "avoid_if_reactive": True,
        "price_eur": 19.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/2312b5c6-0d1b-435e-91a3-ec9c2e56b06b/products/mario-badescu-drying-lotion/mario-badescu-drying-lotion_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/mario-badescu-drying-lotion",
    },
    {
        "id": "cosrx-pimple-patch",
        "moment": "soir",
        "name": "Acne Pimple Master Patch",
        "brand": "COSRX",
        "step": "traitement",
        "key_ingredients": ["Hydrocolloïde"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"imperfections": 2},
        "price_eur": 6.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/de5af235-2da4-4026-b791-1a02f4300d3f/products/cosrx-acne-pimple-master-patch/cosrx-acne-pimple-master-patch_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cosrx-acne-pimple-master-patch",
    },
    {
        "id": "differin-adapalene",
        "moment": "soir",
        "name": "Differin Gel 0.1% (adapalène)",
        "brand": "Differin",
        "step": "traitement",
        "key_ingredients": ["Adapalène 0,1% (rétinoïde)"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "texture": 1},
        "min_age": "25-40",
        "avoid_if_reactive": True,
        "price_eur": 15.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/015de897-2a1d-4b31-946b-888a7d32e48b/products/differin-differin-gel/differin-differin-gel_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/differin-adapalene-gel-0-1",
    },
    {
        "id": "murad-rapid-age-spot",
        "moment": "soir",
        "name": "Rapid Age Spot Correcting Sérum",
        "brand": "Murad",
        "step": "traitement",
        "key_ingredients": ["Hydroquinone alternative", "Glycolique"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"radiance": 3},
        "min_age": "40-60",
        "price_eur": 68.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/8750cdaa-0678-4216-a1e2-7fd26fbe467a/products/murad-rapid-age-spot-correcting-serum/murad-rapid-age-spot-correcting-serum_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/murad-rapid-age-spot-correcting-serum",
    },
    {
        "id": "pc-clinical-retinol",
        "moment": "soir",
        "name": "Clinical 1% Retinol Treatment",
        "brand": "Paula's Choice",
        "step": "traitement",
        "key_ingredients": ["Rétinol 1% (forte dose)"],
        "skin_types": ["Normale", "Mixte"],
        "concerns": {"aging": 3, "texture": 1},
        "min_age": "40-60",
        "avoid_if_reactive": True,
        "price_eur": 64.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/a69133ff-f9df-4daf-aea9-f5b7d8624127/products/paulas-choice-clinical-1-retinol-treatment-2/paulas-choice-clinical-1-retinol-treatment-2_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/paulas-choice-clinical-1-retinol-treatment",
    },
    {
        "id": "lrp-toleriane-sensitive-riche",
        "moment": "matin_soir",
        "name": "Toleriane Sensitive Riche",
        "brand": "La Roche-Posay",
        "step": "hydratant",
        "key_ingredients": ["Prébiotique", "Niacinamide", "Céramide"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 2, "redness": 2},
        "price_eur": 19.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/c596b8c8-fa40-4a07-989f-e20dd919b0da/products/la-roche-posay-toleriane-sensitive-riche/la-roche-posay-toleriane-sensitive-riche_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-toleriane-sensitive-riche",
    },
    {
        "id": "embryolisse-lait-creme",
        "moment": "matin_soir",
        "name": "Lait-Crème Concentré",
        "brand": "Embryolisse",
        "step": "hydratant",
        "key_ingredients": ["Beurre de karité", "Aloe vera"],
        "skin_types": ["Normale", "Sèche", "Mixte", "Grasse"],
        "concerns": {"hydration": 1},
        "price_eur": 15.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/387f719a-5a1c-4119-8dab-bf49efd04dbf/products/embryolisse-lait-creme-concentre/embryolisse-lait-creme-concentre_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/embryolisse-lait-creme-concentre",
    },
    {
        "id": "clinique-dramatically-different-gel",
        "moment": "matin_soir",
        "name": "Dramatically Different Moisturizing Gel",
        "brand": "Clinique",
        "step": "hydratant",
        "key_ingredients": ["Acide hyaluronique", "Caféine"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"hydration": 1},
        "price_eur": 34.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/2d07b091-e647-453c-931a-c76279acf4cf/products/clinique-dramatically-different-moisturizing-gel/clinique-dramatically-different-moisturizing-gel_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/clinique-dramatically-different-moisturizing-gel",
    },
    {
        "id": "kiehls-ultra-facial-cream",
        "moment": "matin_soir",
        "name": "Ultra Facial Cream",
        "brand": "Kiehl's",
        "step": "hydratant",
        "key_ingredients": ["Squalane", "Glacier glycoprotein"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"hydration": 2},
        "price_eur": 36.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/1da656e9-998f-4ece-beac-b9daca507ced/products/kiehls-ultra-facial-cream-7/kiehls-ultra-facial-cream-7_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/kiehls-ultra-facial-cream",
    },
    {
        "id": "fab-ultra-repair-cream",
        "moment": "matin_soir",
        "name": "Ultra Repair Cream",
        "brand": "First Aid Beauty",
        "step": "hydratant",
        "key_ingredients": ["Avoine colloïdale", "Céramides", "Beurre de karité"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 3, "redness": 1},
        "price_eur": 38.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/816eff58-4d3f-43e2-a697-2f97b2adf624/products/first-aid-beauty-ultra-repair-cream/first-aid-beauty-ultra-repair-cream_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/first-aid-beauty-ultra-repair-cream",
    },
    {
        "id": "weleda-skin-food",
        "moment": "soir",
        "name": "Skin Food Crème Nourrissante",
        "brand": "Weleda",
        "step": "hydratant",
        "key_ingredients": ["Calendula", "Camomille", "Huiles végétales"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 2},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/4dd12336-0fba-4704-99cf-f52f62aba164/products/weleda-skin-food/weleda-skin-food_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/weleda-skin-food",
    },
    {
        "id": "belif-aqua-bomb",
        "moment": "matin_soir",
        "name": "The True Cream Aqua Bomb",
        "brand": "belif",
        "step": "hydratant",
        "key_ingredients": ["Complexe d'herbes", "Acide hyaluronique"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"hydration": 2},
        "price_eur": 38.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/7918b2e4-5602-432c-88ac-bffe7badfa6f/products/belif-the-true-cream-aqua-bomb/belif-the-true-cream-aqua-bomb_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/belif-the-true-cream-aqua-bomb",
    },
    {
        "id": "nivea-creme",
        "moment": "soir",
        "name": "Crème Nivea",
        "brand": "Nivea",
        "step": "hydratant",
        "key_ingredients": ["Eucérine", "Huile de jojoba"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 2},
        "price_eur": 5.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/5ffc318c-406b-478c-bcec-48bd0bc50e67/products/nivea-creme-2/nivea-creme-2_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/nivea-creme",
    },
    {
        "id": "cerave-pm-lotion",
        "moment": "soir",
        "name": "Facial Moisturizing Lotion PM",
        "brand": "CeraVe",
        "step": "hydratant",
        "key_ingredients": ["Céramides", "Niacinamide"],
        "skin_types": ["Normale", "Mixte", "Grasse"],
        "concerns": {"hydration": 1, "redness": 1},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/e8d11556-573b-4dc3-9777-90325043c835/products/cerave-facial-moisturizing-lotion-pm/cerave-facial-moisturizing-lotion-pm_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cerave-facial-moisturizing-lotion-pm",
    },
    {
        "id": "lrp-lipikar-baume-ap",
        "moment": "matin_soir",
        "name": "Lipikar Baume AP+",
        "brand": "La Roche-Posay",
        "step": "hydratant",
        "key_ingredients": ["Beurre de karité", "Niacinamide"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 3, "redness": 2},
        "price_eur": 18.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/b8761ec3-ccfa-4007-8aba-ca0dacdb1173/products/la-roche-posay-lipikar-baume-ap/la-roche-posay-lipikar-baume-ap_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-lipikar-baume-ap",
    },
    {
        "id": "lrp-cicaplast-gel-b5",
        "moment": "matin_soir",
        "name": "Cicaplast Gel B5",
        "brand": "La Roche-Posay",
        "step": "hydratant",
        "key_ingredients": ["Panthénol", "Madécassoside"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"redness": 2, "imperfections": 1},
        "price_eur": 11.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/89c7882e-d3ae-4daf-8bd2-81ebac2e8c1a/products/la-roche-posay-cicaplast-gel-b5/la-roche-posay-cicaplast-gel-b5_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-cicaplast-gel-b5",
    },
    {
        "id": "bioderma-cicabio-cream",
        "moment": "matin_soir",
        "name": "Cicabio Crème",
        "brand": "Bioderma",
        "step": "hydratant",
        "key_ingredients": ["Cu-Zn sulfate", "Centella asiatica"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"redness": 2},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/5a6c25f7-4fa5-4ceb-9b79-14ab24e43bca/products/bioderma-cicabio-creme-3/bioderma-cicabio-creme-3_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/bioderma-cicabio-cream",
    },
    {
        "id": "bioderma-atoderm-cream",
        "moment": "matin_soir",
        "name": "Atoderm Crème",
        "brand": "Bioderma",
        "step": "hydratant",
        "key_ingredients": ["Céramides", "Niacinamide"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 3},
        "price_eur": 15.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/e2206123-1c91-4672-99f5-115986f471df/products/bioderma-atoderm-cream/bioderma-atoderm-cream_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/bioderma-atoderm-cream",
    },
    {
        "id": "uriage-bariederm-cica",
        "moment": "matin_soir",
        "name": "Bariéderm Cica Crème",
        "brand": "Uriage",
        "step": "hydratant",
        "key_ingredients": ["Cu-Zn", "Eau thermale d'Uriage"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"redness": 2},
        "price_eur": 13.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/5b86eeef-b054-4e62-ba4f-1e263861c045/products/uriage-bariederm-cica-cream/uriage-bariederm-cica-cream_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/uriage-bariederm-cica-cream",
    },
    {
        "id": "to-squalane-oil",
        "moment": "soir",
        "name": "100% Plant-Derived Squalane",
        "brand": "The Ordinary",
        "step": "hydratant",
        "key_ingredients": ["Squalane végétal pur"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 2},
        "price_eur": 9.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/581a7b5e-5e99-4964-8d2e-ad93488193d0/products/the-ordinary-100-plant-derived-squalane/the-ordinary-100-plant-derived-squalane_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-100-plant-derived-squalane",
    },
    {
        "id": "to-nmf-ha",
        "moment": "matin_soir",
        "name": "Natural Moisturizing Factors + HA",
        "brand": "The Ordinary",
        "step": "hydratant",
        "key_ingredients": ["Facteurs naturels d'hydratation", "Acide hyaluronique"],
        "skin_types": ["Normale", "Sèche", "Mixte"],
        "concerns": {"hydration": 2},
        "price_eur": 8.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/5dc6eb9b-23e1-4169-8301-2900b2fcb73e/products/the-ordinary-natural-moisturizing-factors-ha/the-ordinary-natural-moisturizing-factors-ha_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-natural-moisturizing-factors-ha",
    },
    {
        "id": "to-b-oil",
        "moment": "soir",
        "name": "B Oil",
        "brand": "The Ordinary",
        "step": "hydratant",
        "key_ingredients": ["Huiles végétales", "Vitamine F"],
        "skin_types": ["Sèche"],
        "concerns": {"hydration": 2},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/d7aa6080-4969-4ef4-a7a6-cbfc6e0b4405/products/the-ordinary-b-oil/the-ordinary-b-oil_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/the-ordinary-b-oil",
    },
    {
        "id": "etude-soon-jung-barrier-cream",
        "moment": "matin_soir",
        "name": "SoonJung 2x Barrier Intensive Cream",
        "brand": "Etude House",
        "step": "hydratant",
        "key_ingredients": ["Panthénol", "Madécassoside"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"redness": 2, "hydration": 1},
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/7ee114e4-b0c2-4624-9a85-4c3df064d4db/products/etude-house-soon-jung-2x-barrier-intensive-cream/etude-house-soon-jung-2x-barrier-intensive-cream_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/etude-house-soon-jung-2x-barrier-intensive-cream",
    },
    {
        "id": "eltamd-uv-clear",
        "moment": "matin",
        "name": "UV Clear Broad-Spectrum SPF 46",
        "brand": "EltaMD",
        "step": "protection",
        "key_ingredients": ["Niacinamide", "Oxyde de zinc"],
        "skin_types": ["Mixte", "Grasse", "Normale"],
        "concerns": {"imperfections": 1, "aging": 1},
        "price_eur": 38.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/8a4cff7a-124f-472d-a9c2-747539f90608/products/eltamd-uv-clear-broad-spectrum-spf-46/eltamd-uv-clear-broad-spectrum-spf-46_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/eltamd-uv-clear-broad-spectrum-spf-46",
    },
    {
        "id": "supergoop-unseen",
        "moment": "matin",
        "name": "Unseen Sunscreen SPF 40",
        "brand": "Supergoop",
        "step": "protection",
        "key_ingredients": ["Filtres invisibles", "Base maquillage"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"aging": 1},
        "price_eur": 36.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/4ce1ab88-c365-4a95-a59e-31bde24dc5cb/products/supergoop-unseen-sunscreen-spf-40/supergoop-unseen-sunscreen-spf-40_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/supergoop-unseen-sunscreen-spf-40",
    },
    {
        "id": "lrp-anthelios-age-correct",
        "moment": "matin",
        "name": "Anthelios Age Correct SPF50",
        "brand": "La Roche-Posay",
        "step": "protection",
        "key_ingredients": ["Niacinamide", "Filtres UVA/UVB"],
        "skin_types": ["Normale", "Sèche"],
        "concerns": {"aging": 2, "radiance": 1},
        "min_age": "40-60",
        "price_eur": 21.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/af9cb186-5adc-4ab0-8ff5-57c44b0f7981/products/la-roche-posay-anthelios-age-correct-spf50/la-roche-posay-anthelios-age-correct-spf50_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-anthelios-age-correct-spf50",
    },
    {
        "id": "cerave-am-spf30",
        "moment": "matin",
        "name": "Facial Moisturizing Lotion AM SPF 30",
        "brand": "CeraVe",
        "step": "protection",
        "key_ingredients": ["Céramides", "Niacinamide"],
        "skin_types": ["Normale", "Mixte", "Grasse", "Sèche"],
        "concerns": {"hydration": 1},
        "price_eur": 14.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/6d9d1ca1-4586-4506-abd4-f45afb40227a/products/cerave-am-facial-moisturizing-lotion-spf-30/cerave-am-facial-moisturizing-lotion-spf-30_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cerave-am-facial-moisturizing-lotion-spf-30",
    },
    {
        "id": "kiehls-avocado-eye",
        "moment": "matin_soir",
        "name": "Creamy Eye Treatment with Avocado",
        "brand": "Kiehl's",
        "step": "contour_yeux",
        "key_ingredients": ["Huile d'avocat", "Beurre de karité"],
        "skin_types": ["Sèche", "Normale"],
        "concerns": {"hydration": 2, "aging": 1},
        "price_eur": 39.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/d8bf8e08-cb2c-483a-971e-764d7ebda411/products/kiehls-creamy-eye-treatment-with-avocado/kiehls-creamy-eye-treatment-with-avocado_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/kiehls-creamy-eye-treatment-with-avocado",
    },
    {
        "id": "lrp-pigmentclar-eyes",
        "moment": "matin_soir",
        "name": "Pigmentclar Yeux",
        "brand": "La Roche-Posay",
        "step": "contour_yeux",
        "key_ingredients": ["LHA", "Niacinamide"],
        "skin_types": ["Normale", "Mixte", "Sèche"],
        "concerns": {"radiance": 2},
        "price_eur": 24.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9798f513-179b-4bf4-9ac2-66035c5d6ffc/products/la-roche-posay-pigmentclar-eyes/la-roche-posay-pigmentclar-eyes_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-pigmentclar-eyes",
    },
    {
        "id": "cerave-eye-repair",
        "moment": "matin_soir",
        "name": "Eye Repair Cream",
        "brand": "CeraVe",
        "step": "contour_yeux",
        "key_ingredients": ["Céramides", "Niacinamide", "Hyaluronate de sodium"],
        "skin_types": ["Normale", "Sèche", "Mixte", "Grasse"],
        "concerns": {"hydration": 1, "aging": 1},
        "price_eur": 16.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/f731d150-7cd9-4206-8665-26c9054e256f/products/cerave-eye-repair-cream/cerave-eye-repair-cream_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/cerave-eye-repair-cream",
    },
    {
        "id": "lrp-serozinc",
        "moment": "matin_soir",
        "name": "Sérozinc",
        "brand": "La Roche-Posay",
        "step": "traitement",
        "key_ingredients": ["Sulfate de zinc", "Eau thermale"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2, "redness": 1},
        "price_eur": 12.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/0b968b55-c2db-46dc-ad28-8347ff6bd0aa/products/la-roche-posay-serozinc/la-roche-posay-serozinc_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-serozinc",
    },
    {
        "id": "isdin-fotoprotector-fusion-water",
        "moment": "matin",
        "name": "Fotoprotector Fusion Water SPF50",
        "brand": "ISDIN",
        "step": "protection",
        "key_ingredients": ["Filtres minéraux+organiques", "Texture invisible"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 1, "aging": 1},
        "price_eur": 19.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/9c52dd70-0edc-4844-ba07-0d59c2455571/products/isdin-fotoprotector-isdin-fusion-water-spf-50/isdin-fotoprotector-isdin-fusion-water-spf-50_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/isdin-fotoprotector-isdin-fusion-water-spf-50",
    },
    {
        "id": "lrp-effaclar-duo-unifiant",
        "moment": "soir",
        "name": "Effaclar Duo+ Unifiant",
        "brand": "La Roche-Posay",
        "step": "traitement",
        "key_ingredients": ["Niacinamide", "Acide salicylique", "Pigments correcteurs"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 3, "radiance": 1},
        "price_eur": 18.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/0bca92b9-2bc4-4811-a3c9-710486c6e3f5/products/la-roche-posay-effaclar-duo-unifiant-3/la-roche-posay-effaclar-duo-unifiant-3_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/la-roche-posay-effaclar-duo-unifiant",
    },
    {
        "id": "vichy-normaderm-phytosolution",
        "moment": "matin_soir",
        "name": "Normaderm Phytosolution",
        "brand": "Vichy",
        "step": "hydratant",
        "key_ingredients": ["Acide salicylique", "Acide hyaluronique"],
        "skin_types": ["Mixte", "Grasse"],
        "concerns": {"imperfections": 2, "texture": 1},
        "price_eur": 17.0,
        "image_url": "https://incidecoder-content.storage.googleapis.com/84363f69-af06-48c5-bc5d-ec3116d83960/products/vichy-normaderm-phytosolution/vichy-normaderm-phytosolution_front_photo_300x300@1x.webp",
        "url": "https://incidecoder.com/products/vichy-normaderm-phytosolution",
    },
]

# French templates explaining WHY a product is recommended, per dominant concern
_WHY_TEMPLATES = {
    "hydration": "Votre éclat ({radiance}/100) suggère un déficit d'hydratation — {ing} renforce la rétention d'eau de la barrière cutanée.",
    "radiance": "Ciblé sur votre score d'éclat ({radiance}/100) : {ing} ravive l'uniformité et la luminosité du teint.",
    "texture": "Votre grain de peau ({texture}/100) bénéficiera de {ing} pour lisser progressivement la surface.",
    "imperfections": "Adapté à votre score imperfections ({imperfections}/100) : {ing} régule le sébum et resserre les pores.",
    "redness": "Les micro-rougeurs détectées appellent une réponse apaisante — {ing} calme et répare la barrière cutanée.",
    "aging": "Pour soutenir la fermeté à votre tranche d'âge : {ing} stimule le renouvellement cellulaire.",
}

_GOAL_TO_CONCERN = {
    "hydratation": "hydration",
    "anti-âge": "aging",
    "anti-age": "aging",
    "éclat": "radiance",
    "eclat": "radiance",
    "pores": "imperfections",
}

_PRIORITY_TO_CONCERN = {
    "éclat": "radiance",
    "eclat": "radiance",
    "ridules": "aging",
    "imperfections": "imperfections",
    "sensibilité": "redness",
    "sensibilite": "redness",
}

_AGE_RANK = {"<25": 0, "25-40": 1, "40-60": 2, "60+": 3}


def _user_needs(metrics: Dict[str, float], profile_dict: dict) -> Dict[str, float]:
    """Convert analysis metrics + profile into weighted concern needs (0..1)."""
    tx = float(metrics.get("texture", 80))
    rd = float(metrics.get("radiance", 80))
    im = float(metrics.get("imperfections", 80))
    redness = float(metrics.get("redness", 0.0))
    age = profile_dict.get("age_range") or "25-40"
    env = (profile_dict.get("environment") or "").lower()

    needs = {
        "texture": max(0.0, (100 - tx) / 100),
        "radiance": max(0.0, (100 - rd) / 100),
        "imperfections": max(0.0, (100 - im) / 100),
        # Hydration is inferred: dull + rough skin usually lacks water
        "hydration": max(0.0, ((100 - rd) * 0.6 + (100 - tx) * 0.4) / 100),
        "redness": min(1.0, redness / 10.0),
        "aging": 0.15 + 0.25 * _AGE_RANK.get(age, 1),
    }

    # Environment adjustments
    if "sec" in env:
        needs["hydration"] += 0.15
    if "urbain" in env:
        needs["radiance"] += 0.10

    # Declared goals boost their concern
    for goal in profile_dict.get("goals") or []:
        c = _GOAL_TO_CONCERN.get(str(goal).strip().lower())
        if c:
            needs[c] += 0.15

    # Declared priority boosts its concern
    c = _PRIORITY_TO_CONCERN.get(str(profile_dict.get("priority") or "").strip().lower())
    if c:
        needs[c] += 0.20

    # Sébum mesuré sur la zone T (reflets spéculaires) → besoin de régulation
    shine_t = float(metrics.get("shine_t", 0.0))
    if shine_t > 0.03:
        needs["imperfections"] += min(0.25, shine_t * 2.5)

    # Pores dilatés mesurés (black-hat zone T) → renforce le besoin texture,
    # indépendamment du score global déjà pénalisé
    pore_density = float(metrics.get("pore_density", 0.0))
    if pore_density > 0.02:
        needs["texture"] += min(0.20, pore_density * 3.0)

    # Rides fines mesurées sur le front (photo réelle) : le besoin "aging" ne
    # dépend plus seulement de l'âge déclaré — une évidence photographique
    # concrète pèse davantage qu'une tranche d'âge auto-déclarée
    fine_lines = float(metrics.get("fine_lines", 0.0))
    if fine_lines > 0.15:
        needs["aging"] = min(1.0, needs["aging"] + fine_lines * 0.35)

    return needs


def _score_product(p: dict, needs: Dict[str, float], profile_dict: dict) -> float:
    skin_type = profile_dict.get("skin_type")
    age = profile_dict.get("age_range") or "25-40"
    reactive = needs["redness"] > 0.5

    # Hard safety exclusions
    if p.get("avoid_if_reactive") and reactive:
        return -1.0
    min_age = p.get("min_age")
    if min_age and _AGE_RANK.get(age, 1) < _AGE_RANK.get(min_age, 1):
        return -1.0

    score = sum(w * needs.get(c, 0.0) for c, w in p["concerns"].items())

    # Skin-type affinity: strong signal now that every step of the catalogue
    # offers alternatives per skin type
    if skin_type:
        if skin_type in p["skin_types"]:
            score += 0.8
        else:
            score -= 1.5

    # Tiebreak déterministe par utilisateur : à scores quasi égaux, deux
    # utilisateurs différents ne reçoivent pas la même liste (jitter ≤ 0.15,
    # trop faible pour renverser une vraie préférence)
    uid = str(profile_dict.get("user_id") or "")
    if uid:
        h = int(hashlib.md5(f"{uid}:{p['id']}".encode()).hexdigest()[:6], 16)
        score += (h % 97) / 650.0

    return score


_CONCERN_FR = {
    "hydration": "hydratation",
    "radiance": "éclat",
    "texture": "texture",
    "imperfections": "imperfections",
    "redness": "rougeurs",
    "aging": "fermeté",
}


def _confidence(
    p: dict, needs: Dict[str, float], profile_dict: dict, metrics: Optional[Dict[str, float]] = None,
) -> tuple:
    """Indice de confiance (0-100) façon dermatologue : combien ce produit est
    justifié pour CE profil précis, plus la liste des raisons qui l'expliquent.

    Trois piliers, chacun plafonné :
    - Affinité type de peau (0-40) — le facteur le plus discriminant
    - Alignement avec les besoins mesurés sur la photo (0-40)
    - Contexte utilisateur : priorité déclarée, réactivité, environnement,
      stade de vie (0-20)
    """
    reasons: List[str] = []
    skin_type = profile_dict.get("skin_type")
    age = profile_dict.get("age_range")
    priority = str(profile_dict.get("priority") or "").strip().lower()
    environment = str(profile_dict.get("environment") or "").strip().lower()
    reactive = needs.get("redness", 0.0) > 0.5

    # A. Affinité type de peau
    if skin_type:
        if skin_type in p["skin_types"]:
            skin_pts = 40.0
            reasons.append(f"formulé pour peau {skin_type.lower()}")
        else:
            skin_pts = 8.0
    else:
        skin_pts = 22.0  # type inconnu : score neutre, ni pénalisé ni survalorisé

    # B. Alignement avec les besoins mesurés (texture/éclat/imperfections/...)
    concern_raw = sum(w * needs.get(c, 0.0) for c, w in p["concerns"].items())
    concern_pts = min(40.0, (concern_raw / 3.0) * 40.0)
    if concern_pts >= 22:
        dominant = max(p["concerns"], key=lambda c: p["concerns"][c] * needs.get(c, 0.0))
        reasons.append(f"cible directement votre besoin en {_CONCERN_FR.get(dominant, dominant)}")

    # C. Contexte : réactivité, priorité déclarée, environnement, stade de vie
    ctx_pts = 0.0
    if reactive and not p.get("avoid_if_reactive"):
        ctx_pts += 6.0
        reasons.append("compatible avec une peau réactive")
    elif not reactive:
        ctx_pts += 3.0
    prio_concern = _PRIORITY_TO_CONCERN.get(priority)
    if prio_concern and prio_concern in p["concerns"]:
        ctx_pts += 8.0
        reasons.append("répond à votre priorité déclarée")
    if "sec" in environment and "hydration" in p["concerns"]:
        ctx_pts += 3.0
    elif "urbain" in environment and ("radiance" in p["concerns"] or "imperfections" in p["concerns"]):
        ctx_pts += 3.0
    if age and p.get("min_age") == age:
        ctx_pts += 3.0
        reasons.append("spécifiquement formulé pour votre tranche d'âge")

    # Preuves photographiques directes (pores, rides) quand elles motivent ce produit
    metrics = metrics or {}
    if float(metrics.get("pore_density", 0.0)) > 0.04 and "texture" in p["concerns"]:
        reasons.append("pores dilatés mesurés en zone T sur votre photo")
    if float(metrics.get("fine_lines", 0.0)) > 0.3 and "aging" in p["concerns"]:
        reasons.append("rides d'expression détectées sur le front")

    total = int(round(min(100.0, skin_pts + concern_pts + ctx_pts)))
    return total, reasons


def _confidence_label(score: int) -> str:
    if score >= 85:
        return "Recommandation experte"
    if score >= 65:
        return "Très bonne correspondance"
    if score >= 45:
        return "Bonne correspondance"
    return "Choix complémentaire"


# Steps whose role is structural: the explanation is about the routine, not a score
_STEP_WHY = {
    "nettoyant": "Base de votre routine : {ing} nettoie en douceur sans compromettre la barrière cutanée.",
    "hydratant": "Scelle les actifs appliqués avant lui : {ing} maintient l'hydratation tout au long de la journée.",
    "protection": "Geste non-négociable : {ing} protège du photovieillissement et de l'aggravation des taches.",
}


def _why(p: dict, needs: Dict[str, float], metrics: Dict[str, float]) -> str:
    tpl = _STEP_WHY.get(p["step"])
    if tpl is None:
        dominant = max(p["concerns"], key=lambda c: p["concerns"][c] * needs.get(c, 0.0))
        tpl = _WHY_TEMPLATES.get(dominant, _WHY_TEMPLATES["hydration"])
    return tpl.format(
        ing=", ".join(p["key_ingredients"][:2]),
        texture=int(metrics.get("texture", 80)),
        radiance=int(metrics.get("radiance", 80)),
        imperfections=int(metrics.get("imperfections", 80)),
    )


def buy_url(product: dict) -> str:
    """Lien d'achat pour un produit.

    Le champ `url` du catalogue pointe vers INCIDecoder, une base de
    composition : très utile pour lire la liste INCI complète, mais on n'y
    achète rien. L'utilisateur qui tape sur une carte produit veut pouvoir se
    le procurer.

    On renvoie une recherche marchande plutôt que la fiche d'une boutique
    précise, pour trois raisons : la disponibilité varie d'une enseigne à
    l'autre, une URL de fiche casse dès que le marchand réorganise son
    catalogue, et l'utilisateur voit ainsi plusieurs prix au lieu d'être
    envoyé chez un seul vendeur. Une recherche, elle, résout toujours.
    """
    q = quote_plus(f"{product.get('brand', '')} {product.get('name', '')}".strip())
    return f"https://www.google.com/search?tbm=shop&hl=fr&gl=fr&q={q}"


def recommend_products(
    metrics: Dict[str, float],
    profile_dict: Optional[dict] = None,
    max_actives: int = 2,
) -> List[dict]:
    """Return a personalised 4-5 product routine (nettoyant → SPF).

    Each entry: {id, name, brand, step, step_label, why, key_ingredients,
    price_eur, image_url, url, buy_url}.
    """
    profile_dict = profile_dict or {}
    needs = _user_needs(metrics, profile_dict)

    scored = [(p, _score_product(p, needs, profile_dict)) for p in CATALOG]
    scored = [(p, s) for p, s in scored if s >= 0]
    # Contre-indications absolues (grossesse, isotrétinoïne) : le produit est
    # écarté pour ce qu'il est, avant même toute question de combinaison.
    scored = [(p, s) for p, s in scored
              if not _actives.contraindicated(p, profile_dict)]
    scored.sort(key=lambda x: x[1], reverse=True)

    routine: List[dict] = []
    picked_steps: Dict[str, int] = {}
    quotas = {"nettoyant": 1, "serum": 1, "traitement": 1, "hydratant": 1, "protection": 1}

    # Chaque étape choisissait auparavant son meilleur produit sans regarder
    # les autres : un sérum au rétinol et un traitement au rétinol pouvaient
    # donc atterrir dans la même routine. On vérifie désormais la
    # compatibilité avec ce qui est déjà retenu, et la charge irritante totale.
    budget = _actives.irritation_budget(needs, profile_dict)
    load = 0.0

    # Le socle (nettoyer, hydrater, protéger) ne porte pas d'actif fort et ne
    # doit jamais sauter faute de budget : retirer la protection solaire d'une
    # routine anti-acné serait un contresens, les actifs kératolytiques
    # photosensibilisent la peau.
    essential = ("nettoyant", "hydratant", "protection")

    for p, s in scored:
        step = p["step"]
        if picked_steps.get(step, 0) >= quotas.get(step, 0):
            continue
        if _actives.conflicts(p, routine):
            continue
        cost = _actives.irritation(p)
        if step not in essential and load + cost > budget:
            continue
        picked_steps[step] = picked_steps.get(step, 0) + 1
        routine.append(p)
        load += cost

    # Étape de socle restée vide parce que tous ses candidats ont été écartés :
    # on la remplit avec l'option la plus douce encore compatible, plutôt que
    # de livrer une routine trouée.
    for step in essential:
        if picked_steps.get(step, 0) >= quotas.get(step, 0):
            continue
        fallback = sorted(
            (p for p, s in scored
             if p["step"] == step and not _actives.conflicts(p, routine)),
            key=_actives.irritation,
        )
        if fallback:
            routine.append(fallback[0])
            picked_steps[step] = 1
            load += _actives.irritation(fallback[0])

    # Complément d'actifs, dans la limite du budget et sans incompatibilité
    actives = [p for p in routine if p["step"] in ("serum", "traitement")]
    if len(actives) < max_actives:
        for p, s in scored:
            if p in routine or p["step"] not in ("serum", "traitement"):
                continue
            if _actives.conflicts(p, routine):
                continue
            cost = _actives.irritation(p)
            if load + cost > budget:
                continue
            routine.append(p)
            actives.append(p)
            load += cost
            if len(actives) >= max_actives:
                break

    # Contour des yeux : ajouté seulement quand le signe d'âge le justifie
    # vraiment (stade de vie mature ou fermeté déjà en demande) — pas un
    # produit générique imposé à tout le monde.
    age = profile_dict.get("age_range")
    if needs.get("aging", 0.0) >= 0.45 or age in ("40-60", "60+"):
        for p, s in scored:
            if p["step"] == "contour_yeux" and not _actives.conflicts(p, routine):
                routine.append(p)
                break

    routine.sort(key=lambda p: STEP_ORDER.index(p["step"]))

    out = []
    for p in routine:
        confidence, reasons = _confidence(p, needs, profile_dict, metrics)
        out.append({
            "id": p["id"],
            "name": p["name"],
            "brand": p["brand"],
            "step": p["step"],
            "step_label": STEP_LABELS[p["step"]],
            "moment": p.get("moment", "matin_soir"),
            "moment_label": {"matin": "Matin", "soir": "Soir", "matin_soir": "Matin & soir"}[p.get("moment", "matin_soir")],
            "why": _why(p, needs, metrics),
            "match_confidence": confidence,
            "confidence_label": _confidence_label(confidence),
            "match_reasons": reasons,
            "key_ingredients": p["key_ingredients"],
            "price_eur": p["price_eur"],
            "image_url": p["image_url"],
            # `url` = fiche composition (liste INCI complete) ;
            # `buy_url` = ou se le procurer reellement.
            "url": p["url"],
            "buy_url": buy_url(p),
        })
    return out
