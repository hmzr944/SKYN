/**
 * Dictionnaire français — langue source de l'app, donc aussi la valeur de
 * repli : une clé absente d'`en.ts` retombe ici plutôt que d'afficher la clé
 * brute, pour qu'un oubli de traduction reste lisible au lieu de casser
 * l'écran.
 */
const fr = {
  common: {
    back: "Retour",
    cancel: "Annuler",
    delete: "Supprimer",
    close: "Fermer",
    retry: "Réessayer",
    you: "Vous",
  },
  settings: {
    title: "Réglages",
    language: "Langue",
    languageHint: "Change la langue de toute l'application",
    french: "Français",
    english: "English",
    remindersSection: "Rappels",
    remindersUnsupported:
      "Les rappels demandent des notifications programmées, que le navigateur ne sait pas faire. Ils s'activeront dans l'application installée.",
    remindersMorning: "Le matin",
    remindersMorningHint: "Nettoyant, soin, protection solaire",
    remindersEvening: "Le soir",
    remindersEveningHint: "Le moment qui compte le plus",
    remindersToggleLabel: "Rappel {label}",
    bumpTimeLabel: "Décaler l'heure, actuellement {time}",
    dataSection: "Vos données",
    statScans: "analyses",
    statJournalDays: "jours notés",
    statFollowups: "suivis",
    statKo: "Ko",
    exportData: "Exporter mes données",
    exportHint: "Copie tout au format JSON",
    exportedTitle: "Données copiées",
    exportedBody:
      "Vos analyses, votre journal et vos suivis sont dans le presse-papier, au format JSON. Collez-les où vous voulez les conserver.",
    eraseData: "Supprimer mes données",
    eraseHint: "Définitif, immédiat, sur cet appareil",
    eraseConfirmTitle: "Tout supprimer ?",
    eraseConfirmBody:
      "Cela supprime vos analyses, votre journal, vos suivis et vos réglages. C'est définitif et immédiat.",
    erasedTitle: "Données supprimées",
    erasedBody: "{count} entrées effacées de cet appareil.",
    deleteAccount: "Supprimer mon compte",
    deleteAccountHint: "Ferme le compte et efface aussi la copie en ligne",
    deleteAccountConfirmTitle: "Supprimer votre compte ?",
    deleteAccountConfirmBody:
      "Cela ferme votre compte et supprime vos analyses, ici et en ligne. C'est définitif : rien ne pourra être récupéré.",
    deletionTitle: "Suppression",
    legalSection: "Confidentialité et cadre légal",
    foldDataTitle: "Où vont vos données",
    foldDataBody:
      "Vos analyses, votre journal et vos suivis sont stockés sur cet appareil, pas sur nos serveurs.\n\nVos photos partent au moteur d'analyse le temps du calcul, puis sont effacées de l'appareil. Elles ne sont ni conservées ni réutilisées pour entraîner quoi que ce soit.\n\nSi vous avez un compte, seuls votre identifiant et vos scores de synthèse sont sauvegardés pour vous les retrouver sur un autre appareil.",
    foldMedicalTitle: "Avertissement médical",
    foldMedicalBody:
      "SKYN est un outil de mesure et de suivi. Ce n'est pas un dispositif médical et il ne pose aucun diagnostic.\n\nLes lectures qu'il propose décrivent ce qui est fréquent ou inhabituel, jamais une certitude. Elles ne remplacent pas l'avis d'un dermatologue.\n\nConsultez sans attendre en cas de douleur, de gonflement, de lésions qui s'étendent, ou si une réaction apparaît après un nouveau produit.",
    foldMinorsTitle: "Utilisation par un mineur",
    foldMinorsBody:
      "L'acné touche surtout les adolescents, et l'app leur est destinée.\n\nEn dessous de 15 ans, le consentement d'un parent est requis pour le traitement des données en France. Les données restant sur l'appareil, aucun profil n'est constitué de notre côté.",
    foldRightsTitle: "Vos droits",
    foldRightsBody:
      "Accès, rectification, effacement, portabilité : ces droits s'exercent directement depuis la section « Vos données » ci-dessus, sans avoir à nous écrire ni à nous croire sur parole.\n\nL'export vous rend l'intégralité de ce qui est conservé.\n\n« Supprimer mes données » efface ce qui est sur cet appareil. « Supprimer mon compte » ferme en plus le compte et efface la copie en ligne de vos scores. L'app vous dit ensuite ce qui a réellement été supprimé, y compris si quelque chose a échoué.",
    aboutSection: "À propos",
    foldEngineTitle: "Comment l'analyse fonctionne",
    foldEngineBody:
      "Le moteur repère 468 points du visage, en déduit 13 zones, et écarte sourcils, cils, lèvres et narines du calcul.\n\nIl compte les lésions et les classe par signature colorimétrique, estime le type de peau par différence de brillance entre zone T et zone U, et le phototype par angle typologique.\n\nLes produits sont ensuite appariés à ce relevé, avec un niveau de preuve affiché pour chacun et un contrôle des incompatibilités d'actifs.",
    foldLicensesTitle: "Licences",
    foldLicensesBody:
      "Outfit, de Rodrigo Fuenzalida, sous SIL Open Font License 1.1.\n\nFraunces, de Undercase Type, sous SIL Open Font License 1.1.\n\nMediaPipe (guidage du cadrage), de Google, licence Apache 2.0.\n\nOpenCV, SciPy et NumPy, licences BSD.\n\nReact Native et Expo, licence MIT.",
    legalDocs: "Documents légaux",
    legalDocsHint: "Confidentialité, mentions légales, conditions",
    legalUnavailableTitle: "Page indisponible",
    legalUnavailableBody:
      "Impossible d'ouvrir le navigateur. Les points essentiels restent dépliables ci-dessus.",
    version: "Version",
    footNote: "SKYN n'est pas un dispositif médical et ne remplace pas un avis dermatologique.",
  },
  dashboard: {
    greeting: "Bonjour, {name}.",
    heroTitleF: "Prête à comprendre\nvotre peau ?",
    heroTitleM: "Prêt à comprendre\nvotre peau ?",
    heroTitleN: "On commence à\ncomprendre votre peau ?",
    heroSubtitle: "Un premier scan pour commencer à comprendre comment elle évolue.",
    startAnalysis: "Faire mon premier scan",
    lastScan: "DERNIER SCAN",
    max100: "/ 100",
    skinLabel: "Peau",
    lesionsLabel: "Lésions",
    chartTitle: "ÉVOLUTION SUR {count} SCAN{s}",
    chartEmpty: "La courbe apparaîtra dès votre premier bilan.",
    tipsTitle: "Conseils du jour",
    analyzeSkin: "Analyser ma peau",
    discoverSkinMap: "Voir ma mémoire de peau",
    synced: "{count} bilan{s} synchronisé{s}.",
    tip1: "Hydratez votre peau matin et soir avec une crème adaptée à votre type de peau.",
    tip2: "Appliquez une protection solaire SPF 30+ chaque matin, même par temps couvert.",
    tip3: "Buvez au moins 1,5L d'eau par jour pour soutenir l'hydratation cutanée.",
    tip4: "Évitez de toucher votre visage pour limiter le transfert de bactéries.",
    tip5: "Démaquillez-vous systématiquement avant de dormir.",
    tip6: "Privilégiez un nettoyant doux, sans sulfates agressifs.",
  },
} as const;

export default fr;

/** Le meme arbre de cles que fr, mais toute feuille redevient `string` —
 * sinon `en.ts` ne pourrait jamais typer ses propres valeurs (differentes
 * par definition) contre le dictionnaire francais. */
type DeepString<T> = T extends string ? string : { [K in keyof T]: DeepString<T[K]> };
export type Dictionary = DeepString<typeof fr>;
