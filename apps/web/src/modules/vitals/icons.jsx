// Icons used only by the vitals module. Decorative (aria-hidden), stroke style matching src/icons.jsx.

function Svg({ size = 18, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Pulse = (p) => (
  <Svg {...p}>
    <path d="M3 12h4l2-5 4 10 2-5h6" />
  </Svg>
);

export const Camera = (p) => (
  <Svg {...p}>
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </Svg>
);

export const Device = (p) => (
  <Svg {...p}>
    <rect x="6" y="3" width="12" height="18" rx="3" />
    <path d="M10 17h4" />
    <path d="M9 8h6v4H9z" />
  </Svg>
);

export const Upload = (p) => (
  <Svg {...p}>
    <path d="M12 16V4" />
    <path d="M7 9l5-5 5 5" />
    <path d="M4 20h16" />
  </Svg>
);

export const Clock = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </Svg>
);
