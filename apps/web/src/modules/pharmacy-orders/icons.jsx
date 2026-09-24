// Icons used only by online ordering. Decorative (aria-hidden), stroke style matching src/icons.jsx.

function Svg({ size = 18, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Bag = (p) => (
  <Svg {...p}>
    <path d="M5 8h14l-1 12H6z" />
    <path d="M9 8V6a3 3 0 0 1 6 0v2" />
  </Svg>
);

export const Truck = (p) => (
  <Svg {...p}>
    <path d="M2 6h11v10H2z" />
    <path d="M13 9h4l3 3v4h-7" />
    <circle cx="6" cy="17.5" r="1.8" />
    <circle cx="17" cy="17.5" r="1.8" />
  </Svg>
);

export const Clipboard = (p) => (
  <Svg {...p}>
    <rect x="5" y="4" width="14" height="17" rx="2" />
    <path d="M9 4h6v3H9z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);
