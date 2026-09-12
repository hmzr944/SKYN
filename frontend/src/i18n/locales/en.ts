import type { Dictionary } from "./fr";

/** Traduction anglaise — mêmes clés que fr.ts, vérifié par un test qui
 * compare les deux arbres (voir src/i18n/__tests__ si présent, sinon
 * TypeScript le fait déjà via `satisfies Dictionary`). */
const en = {
  common: {
    back: "Back",
    cancel: "Cancel",
    delete: "Delete",
    close: "Close",
    retry: "Retry",
    you: "You",
  },
  settings: {
    title: "Settings",
    language: "Language",
    languageHint: "Changes the language for the whole app",
    french: "Français",
    english: "English",
    remindersSection: "Reminders",
    remindersUnsupported:
      "Reminders need scheduled notifications, which the browser can't do. They'll work once the app is installed.",
    remindersMorning: "Morning",
    remindersMorningHint: "Cleanser, treatment, sun protection",
    remindersEvening: "Evening",
    remindersEveningHint: "The moment that matters most",
    remindersToggleLabel: "{label} reminder",
    bumpTimeLabel: "Change the time, currently {time}",
    dataSection: "Your data",
    statScans: "scans",
    statJournalDays: "days logged",
    statFollowups: "follow-ups",
    statKo: "KB",
    exportData: "Export my data",
    exportHint: "Copies everything as JSON",
    exportedTitle: "Data copied",
    exportedBody:
      "Your scans, journal and follow-ups are on your clipboard, as JSON. Paste them wherever you want to keep them.",
    eraseData: "Delete my data",
    eraseHint: "Permanent, immediate, on this device",
    eraseConfirmTitle: "Delete everything?",
    eraseConfirmBody:
      "This deletes your scans, journal, follow-ups and settings. It's permanent and immediate.",
    erasedTitle: "Data deleted",
    erasedBody: "{count} entries erased from this device.",
    deleteAccount: "Delete my account",
    deleteAccountHint: "Closes the account and erases the online copy too",
    deleteAccountConfirmTitle: "Delete your account?",
    deleteAccountConfirmBody:
      "This closes your account and deletes your scans, here and online. It's permanent: nothing can be recovered.",
    deletionTitle: "Deletion",
    legalSection: "Privacy and legal",
    foldDataTitle: "Where your data goes",
    foldDataBody:
      "Your scans, journal and follow-ups are stored on this device, not on our servers.\n\nYour photos go to the analysis engine for the duration of the computation, then are erased from the device. They are neither kept nor reused to train anything.\n\nIf you have an account, only your ID and summary scores are saved, so you can find them on another device.",
    foldMedicalTitle: "Medical disclaimer",
    foldMedicalBody:
      "SKYN is a measurement and tracking tool. It is not a medical device and does not diagnose anything.\n\nThe readings it offers describe what's common or unusual, never a certainty. They don't replace a dermatologist's opinion.\n\nSeek care promptly for pain, swelling, spreading lesions, or a reaction after a new product.",
    foldMinorsTitle: "Use by a minor",
    foldMinorsBody:
      "SKYN may include features related to skin tracking. To protect minors, some uses require parental consent under applicable rules.\n\nUnder 15, a parent's consent is required for data processing in France. Since data stays on the device, no profile is built on our side.",
    foldRightsTitle: "Your rights",
    foldRightsBody:
      "Access, correction, erasure, portability: these rights are exercised directly from the \"Your data\" section above, without having to write to us or take our word for it.\n\nThe export gives you everything that's kept.\n\n\"Delete my data\" erases what's on this device. \"Delete my account\" also closes the account and erases the online copy of your scores. The app then tells you what was actually deleted, including if something failed.",
    aboutSection: "About",
    foldEngineTitle: "How the analysis works",
    foldEngineBody:
      "The engine locates 468 points on the face, derives 13 zones from them, and excludes eyebrows, eyelashes, lips and nostrils from the computation.\n\nIt counts lesions and classifies them by color signature, estimates skin type from the shine difference between the T-zone and U-zone, and phototype from the typological angle.\n\nProducts are then matched to this reading, with an evidence level shown for each and a check for incompatible ingredients.",
    foldLicensesTitle: "Licenses",
    foldLicensesBody:
      "Outfit, by Rodrigo Fuenzalida, under the SIL Open Font License 1.1.\n\nFraunces, by Undercase Type, under the SIL Open Font License 1.1.\n\nMediaPipe (framing guidance), by Google, Apache 2.0 license.\n\nOpenCV, SciPy and NumPy, BSD licenses.\n\nReact Native and Expo, MIT license.",
    legalDocs: "Legal documents",
    legalDocsHint: "Privacy, legal notice, terms",
    legalUnavailableTitle: "Page unavailable",
    legalUnavailableBody: "Couldn't open the browser. The key points are still available above.",
    version: "Version",
    footNote: "SKYN is not a medical device and does not replace a dermatologist's opinion.",
  },
  dashboard: {
    greeting: "Hello, {name}.",
    heroTitleF: "Ready to understand\nyour skin?",
    heroTitleM: "Ready to understand\nyour skin?",
    heroTitleN: "Shall we start\nunderstanding your skin?",
    heroSubtitle: "A first scan to start understanding how it changes.",
    startAnalysis: "Take my first scan",
    lastScan: "LAST SCAN",
    max100: "/ 100",
    skinLabel: "Skin",
    lesionsLabel: "Lesions",
    chartTitle: "TREND OVER {count} SCAN{s}",
    chartEmpty: "The chart appears after your first scan.",
    tipsTitle: "Tips of the day",
    analyzeSkin: "Scan my skin",
    discoverSkinMap: "See my skin memory",
    synced: "{count} scan{s} synced.",
    tip1: "Moisturize your skin morning and evening with a cream suited to your skin type.",
    tip2: "Apply SPF 30+ sun protection every morning, even on cloudy days.",
    tip3: "Drink at least 1.5L of water a day to support skin hydration.",
    tip4: "Avoid touching your face to limit bacteria transfer.",
    tip5: "Always remove your makeup before sleeping.",
    tip6: "Favor a gentle cleanser, free of harsh sulfates.",
  },
} as const satisfies Dictionary;

export default en;
