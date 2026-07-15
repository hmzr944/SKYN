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

# Routine steps, in application order
STEP_ORDER = ["nettoyant", "serum", "traitement", "hydratant", "protection"]

STEP_LABELS = {
    "nettoyant": "Nettoyant",
    "serum": "Sérum",
    "traitement": "Traitement ciblé",
    "hydratant": "Hydratant",
    "protection": "Protection solaire",
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


def recommend_products(
    metrics: Dict[str, float],
    profile_dict: Optional[dict] = None,
    max_actives: int = 2,
) -> List[dict]:
    """Return a personalised 4-5 product routine (nettoyant → SPF).

    Each entry: {id, name, brand, step, step_label, why, key_ingredients,
    price_eur, image_url, url}.
    """
    profile_dict = profile_dict or {}
    needs = _user_needs(metrics, profile_dict)

    scored = [(p, _score_product(p, needs, profile_dict)) for p in CATALOG]
    scored = [(p, s) for p, s in scored if s >= 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    routine: List[dict] = []
    picked_steps: Dict[str, int] = {}
    quotas = {"nettoyant": 1, "serum": 1, "traitement": 1, "hydratant": 1, "protection": 1}

    # One product per step, best-scored first
    for p, s in scored:
        step = p["step"]
        if picked_steps.get(step, 0) >= quotas.get(step, 0):
            continue
        picked_steps[step] = picked_steps.get(step, 0) + 1
        routine.append(p)

    # If some steps had no eligible product, complete with the next best actives
    actives = [p for p in routine if p["step"] in ("serum", "traitement")]
    if len(actives) < max_actives:
        for p, s in scored:
            if p in routine or p["step"] not in ("serum", "traitement"):
                continue
            routine.append(p)
            actives.append(p)
            if len(actives) >= max_actives:
                break

    routine.sort(key=lambda p: STEP_ORDER.index(p["step"]))

    return [
        {
            "id": p["id"],
            "name": p["name"],
            "brand": p["brand"],
            "step": p["step"],
            "step_label": STEP_LABELS[p["step"]],
            "moment": p.get("moment", "matin_soir"),
            "moment_label": {"matin": "Matin", "soir": "Soir", "matin_soir": "Matin & soir"}[p.get("moment", "matin_soir")],
            "why": _why(p, needs, metrics),
            "key_ingredients": p["key_ingredients"],
            "price_eur": p["price_eur"],
            "image_url": p["image_url"],
            "url": p["url"],
        }
        for p in routine
    ]
