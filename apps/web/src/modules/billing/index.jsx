import "./styles.css";
import Billing from "./Billing.jsx";
import Receipt from "./Receipt.jsx";
import AdminBilling from "./AdminBilling.jsx";
import { Wallet } from "./icons.jsx";

export default {
  id: "billing",
  title: "Bills & coverage",
  group: "Money",
  order: 50,
  routes: [
    { path: "/billing", element: <Billing />, roles: ["patient"] },
    { path: "/billing/receipts/:paymentId", element: <Receipt />, roles: ["patient"] },
    { path: "/admin/billing", element: <AdminBilling />, roles: ["admin"] },
  ],
  nav: [
    { to: "/billing", label: "Bills & coverage", description: "Estimates, claims, payments and assistance",
      roles: ["patient"], placement: "hub" },
    { to: "/admin/billing", label: "Financial assistance", description: "Review patient assistance applications",
      roles: ["admin"], placement: "workspace", icon: Wallet, group: "Billing" },
  ],
};
