/**
 * Jeu d'icônes en trait, dessinées à la main.
 *
 * Les emoji rendaient l'interface peu lisible : rendu variable selon la
 * plateforme, impossible à colorer, et registre visuel enfantin. Ces icônes
 * SVG héritent de `currentColor` et suivent donc le thème.
 */

const base = {
  width: 20,
  height: 20,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
};

export const IconData = (p) => (
  <svg {...base} {...p}>
    <ellipse cx="12" cy="5" rx="8" ry="3" />
    <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
    <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
  </svg>
);

export const IconLayers = (p) => (
  <svg {...base} {...p}>
    <path d="M12 2 2 7l10 5 10-5-10-5Z" />
    <path d="m2 17 10 5 10-5" />
    <path d="m2 12 10 5 10-5" />
  </svg>
);

export const IconAnalysis = (p) => (
  <svg {...base} {...p}>
    <path d="M3 3v16a2 2 0 0 0 2 2h16" />
    <path d="m7 15 3.5-4 3 3L20 7" />
    <circle cx="20" cy="7" r="1.6" />
  </svg>
);

export const IconSatellite = (p) => (
  <svg {...base} {...p}>
    <path d="m7 7 3-3 4 4-3 3-4-4Z" />
    <path d="m14 14 3-3 4 4-3 3-4-4Z" />
    <path d="m9 11 4 4" />
    <path d="M5 17a3.5 3.5 0 0 0 3 3" />
    <path d="M3 20a6.5 6.5 0 0 0 6 3" />
  </svg>
);

export const IconAgriculture = (p) => (
  <svg {...base} {...p}>
    <path d="M12 21V9" />
    <path d="M12 12c0-3 2-5 5-5 0 3-2 5-5 5Z" />
    <path d="M12 16c0-3-2-5-5-5 0 3 2 5 5 5Z" />
    <path d="M8 21h8" />
  </svg>
);

export const IconLand = (p) => (
  <svg {...base} {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20h14V9.5" />
    <path d="M10 20v-6h4v6" />
  </svg>
);

export const IconAssistant = (p) => (
  <svg {...base} {...p}>
    <path d="M21 12a8 8 0 0 1-8 8H7l-4 3V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z" />
    <circle cx="9.5" cy="12" r="0.9" fill="currentColor" stroke="none" />
    <circle cx="13" cy="12" r="0.9" fill="currentColor" stroke="none" />
    <circle cx="16.5" cy="12" r="0.9" fill="currentColor" stroke="none" />
  </svg>
);

export const IconKey = (p) => (
  <svg {...base} {...p}>
    <circle cx="7.5" cy="15.5" r="4" />
    <path d="m10.5 12.5 8-8" />
    <path d="m16 7 2.5 2.5" />
    <path d="m19 4 2 2" />
  </svg>
);

export const IconGuide = (p) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.6-2.5 2.6" />
    <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
  </svg>
);

export const IconSearch = (p) => (
  <svg {...base} width="14" height="14" {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);

export const IconSun = (p) => (
  <svg {...base} width="16" height="16" {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);

export const IconMoon = (p) => (
  <svg {...base} width="16" height="16" {...p}>
    <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />
  </svg>
);

export const IconMenu = (p) => (
  <svg {...base} width="18" height="18" {...p}>
    <path d="M3 6h18M3 12h18M3 18h18" />
  </svg>
);

export const IconExternal = (p) => (
  <svg {...base} width="12" height="12" {...p}>
    <path d="M15 3h6v6" />
    <path d="M10 14 21 3" />
    <path d="M21 14v7H3V3h7" />
  </svg>
);

export const IconCheck = (p) => (
  <svg {...base} width="14" height="14" {...p}>
    <path d="m4 12 5 5L20 6" />
  </svg>
);

export const IconChevron = (p) => (
  <svg {...base} width="14" height="14" {...p}>
    <path d="m6 9 6 6 6-6" />
  </svg>
);

/** Association identifiant d'onglet → composant. */
export const TAB_ICONS = {
  data: IconData,
  layers: IconLayers,
  analysis: IconAnalysis,
  thematic: IconSatellite,
  agriculture: IconAgriculture,
  land: IconLand,
  agent: IconAssistant,
  credentials: IconKey,
  about: IconGuide,
};
