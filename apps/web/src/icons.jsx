// Stroke icons, sized by the caller. Decorative by default (aria-hidden).

function Svg({ size = 18, strokeWidth = 2, children, ...rest }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const Logo = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M12 3v18" />
    <path d="M3 12h18" />
    <circle cx="12" cy="12" r="4" />
  </Svg>
);
export const Shield = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);
export const Arrow = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M5 12h14" />
    <path d="M13 6l6 6-6 6" />
  </Svg>
);
export const Chevron = (p) => (
  <Svg {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
);
export const Back = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Svg>
);
export const Warning = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M12 3l10 18H2z" />
    <path d="M12 10v4" />
    <path d="M12 17h.01" />
  </Svg>
);
export const Calendar = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <rect x="3" y="5" width="18" height="16" rx="2" />
    <path d="M3 10h18" />
    <path d="M8 3v4" />
    <path d="M16 3v4" />
  </Svg>
);
export const Pin = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z" />
    <circle cx="12" cy="10" r="2.5" />
  </Svg>
);
export const Check = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M5 12l5 5L20 7" />
  </Svg>
);
export const Up = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M12 19V5" />
    <path d="M6 11l6-6 6 6" />
  </Svg>
);
export const Down = (p) => (
  <Svg strokeWidth={2.6} {...p}>
    <path d="M12 5v14" />
    <path d="M6 13l6 6 6-6" />
  </Svg>
);
export const Phone = (p) => (
  <Svg {...p}>
    <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
  </Svg>
);
export const Person = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21a8 8 0 0 1 16 0" />
  </Svg>
);
export const Stethoscope = (p) => (
  <Svg {...p}>
    <path d="M6 3v6a6 6 0 0 0 12 0V3" />
    <path d="M12 15v3a3 3 0 0 0 6 0v-1" />
    <circle cx="18" cy="15" r="2" />
  </Svg>
);
export const Hospital = (p) => (
  <Svg {...p}>
    <rect x="3" y="7" width="18" height="14" rx="2" />
    <path d="M9 7V4h6v3" />
    <path d="M12 11v6" />
    <path d="M9 14h6" />
  </Svg>
);
export const Sparkle = (p) => (
  <Svg strokeWidth={2.4} {...p}>
    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" />
  </Svg>
);
export const Book = (p) => (
  <Svg {...p}>
    <path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z" />
    <path d="M4 19a2 2 0 0 0 2 2h13" />
  </Svg>
);
export const Gear = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
  </Svg>
);
export const Inbox = (p) => (
  <Svg {...p}>
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </Svg>
);
export const Chat = (p) => (
  <Svg {...p}>
    <path d="M4 5h16v11H8l-4 4z" />
  </Svg>
);
export const Plus = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </Svg>
);
export const Close = (p) => (
  <Svg strokeWidth={2.2} {...p}>
    <path d="M6 6l12 12" />
    <path d="M18 6L6 18" />
  </Svg>
);
export const Lock = (p) => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </Svg>
);
export const Heart = (p) => (
  <Svg {...p}>
    <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
  </Svg>
);
export const Rx = (p) => (
  <Svg {...p}>
    <path d="M12 4v16M5 8l14 8M19 8L5 16" />
  </Svg>
);
export const Card = (p) => (
  <Svg {...p}>
    <rect x="3" y="6" width="18" height="12" rx="2" />
    <path d="M3 10h18M7 15h4" />
  </Svg>
);
