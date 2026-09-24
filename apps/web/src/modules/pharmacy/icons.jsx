// Icons used only by the pharmacy module. Decorative (aria-hidden), stroke style matching src/icons.jsx.

function Svg({ size = 18, children }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Pill = (p) => (
  <Svg {...p}>
    <rect x="3" y="8.5" width="18" height="7" rx="3.5" transform="rotate(-45 12 12)" />
    <path d="M8.5 8.5l7 7" />
  </Svg>
);

export const Store = (p) => (
  <Svg {...p}>
    <path d="M4 10v10h16V10" />
    <path d="M3 10l2-6h14l2 6z" />
    <path d="M10 20v-5h4v5" />
  </Svg>
);

export const Refresh = (p) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 1 0-2.3 5.7" />
    <path d="M20 4v7h-7" />
  </Svg>
);
