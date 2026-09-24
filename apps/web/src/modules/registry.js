// Every folder in src/modules with an index.jsx is a module. Adding one needs no edits elsewhere.
//
// A module's index.jsx default-exports:
//   {
//     id: "billing",                      // unique
//     title: "Bills & coverage",          // shown on the hub
//     group: "Money",                     // hub section heading
//     order: 50,                          // sort order within the app
//     routes: [{ path: "/billing", element: <Billing />, roles: ["patient"] }],
//     nav: [{
//       to: "/billing", label: "Bills & coverage",
//       description: "Estimates, claims and payments",   // one line on the hub card
//       roles: ["patient"],                              // who sees it
//       placement: "hub" | "top" | "workspace",          // hub card, top bar, or clinician/admin side nav
//       home: false,                                     // true: where this role lands after sign-in
//     }],
//   }

const found = import.meta.glob("./*/index.jsx", { eager: true });

export const MODULES = Object.values(found)
  .map((m) => m.default)
  .filter(Boolean)
  .sort((a, b) => (a.order ?? 100) - (b.order ?? 100) || a.id.localeCompare(b.id));

export function moduleRoutes() {
  return MODULES.flatMap((m) => (m.routes || []).map((r) => ({ ...r, moduleId: m.id })));
}

export function navFor(role, placement) {
  return MODULES.flatMap((m) =>
    (m.nav || [])
      .filter((n) => (!n.roles || n.roles.includes(role)) && (!placement || (n.placement || "hub") === placement))
      .map((n) => ({ ...n, group: n.group || m.group || "More", moduleId: m.id })),
  );
}

export function homeFor(role) {
  const fixed = { patient: "/app", clinician: "/clinician" };
  const fromModule = MODULES.flatMap((m) => m.nav || []).find((n) => n.home && (n.roles || []).includes(role));
  return fromModule?.to || fixed[role] || "/hub";
}

// Panels a module adds to the clinician's patient view. Each: { id, title, order, component }.
// `component` receives { patientId } and renders inside the brief's left column.
export function workspacePanels() {
  return MODULES.flatMap((m) => (m.workspacePanels || []).map((p) => ({ ...p, moduleId: m.id })))
    .sort((a, b) => (a.order ?? 100) - (b.order ?? 100));
}
