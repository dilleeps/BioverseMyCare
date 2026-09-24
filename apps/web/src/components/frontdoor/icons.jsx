// Icons used only by the front-door access components (same stroke style as src/icons.jsx).
function Svg({ size = 20, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Mic = (p) => (
  <Svg {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0" />
    <path d="M12 18v3" />
  </Svg>
);
export const Stop = (p) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </Svg>
);
export const Camera = (p) => (
  <Svg {...p}>
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </Svg>
);
export const Speaker = (p) => (
  <Svg {...p}>
    <path d="M4 10v4h4l5 4V6L8 10z" />
    <path d="M16.5 8.5a5 5 0 0 1 0 7" />
    <path d="M19 6a8.5 8.5 0 0 1 0 12" />
  </Svg>
);
export const Search = (p) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Svg>
);
export const Pill = (p) => (
  <Svg {...p}>
    <rect x="3" y="8.5" width="18" height="7" rx="3.5" transform="rotate(-35 12 12)" />
    <path d="M9.5 8.3l5 7.4" />
  </Svg>
);
export const Skin = (p) => (
  <Svg {...p}>
    <path d="M7 21V11a2 2 0 0 1 4 0V5a2 2 0 0 1 4 0v6a2 2 0 0 1 4 0v5a5 5 0 0 1-5 5z" />
    <circle cx="13" cy="15" r="1" />
  </Svg>
);
export const Report = (p) => (
  <Svg {...p}>
    <path d="M6 3h9l4 4v14H6z" />
    <path d="M9 11h7M9 15h7M9 7h3" />
  </Svg>
);
export const TextSize = (p) => (
  <Svg {...p}>
    <path d="M3 19l5-13 5 13M5 14h6" />
    <path d="M14 19l3.5-8 3.5 8M15.2 16.5h4.6" />
  </Svg>
);
