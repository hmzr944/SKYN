# Les pages légales de SKYN

Trois documents, publiés par GitHub Pages en même temps que l'application :

| Fichier | URL une fois publié | À quoi ça sert |
|---|---|---|
| `confidentialite.html` | `/SKYN/legal/confidentialite.html` | Exigée par l'App Store et le Play Store. |
| `mentions-legales.html` | `/SKYN/legal/mentions-legales.html` | Exigée en France par la LCEN. |
| `conditions.html` | `/SKYN/legal/conditions.html` | Le cadre d'usage, et la limite médicale. |

## À COMPLÉTER AVANT PUBLICATION

Les trois fichiers contiennent des marqueurs `[[À COMPLÉTER : ...]]`. Ils sont
volontairement visibles : un document légal avec un trou est moins dangereux
qu'un document légal avec une invention.

Cherche-les :

    grep -rn "À COMPLÉTER" legal/

Il faut y mettre : ton identité d'éditeur (ou celle de la structure), une
adresse de contact, et l'hébergeur. Ce sont des mentions obligatoires, et je
n'ai aucun moyen de les deviner.
