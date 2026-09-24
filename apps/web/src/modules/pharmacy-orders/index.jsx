import "./styles.css";
import Shop from "./Shop.jsx";
import Checkout from "./Checkout.jsx";
import { OrderDetail, Orders } from "./Orders.jsx";
import { PharmacistOrder, PharmacistQueue } from "./Pharmacist.jsx";
import { Clipboard } from "./icons.jsx";

export default {
  id: "pharmacy-orders",
  title: "Order medicines",
  group: "Care",
  order: 56,
  routes: [
    { path: "/shop", element: <Shop />, roles: ["patient"] },
    { path: "/shop/checkout", element: <Checkout />, roles: ["patient"] },
    { path: "/shop/orders", element: <Orders />, roles: ["patient"] },
    { path: "/shop/orders/:orderId", element: <OrderDetail />, roles: ["patient"] },
    { path: "/pharmacy-orders", element: <PharmacistQueue />, roles: ["staff"] },
    { path: "/pharmacy-orders/:orderId", element: <PharmacistOrder />, roles: ["staff"] },
  ],
  nav: [
    { to: "/shop", label: "Order medicines", description: "Home delivery or clinic pickup for prescriptions and health products",
      roles: ["patient"], placement: "hub" },
    { to: "/pharmacy-orders", label: "Pharmacy orders", description: "Verify, pack and deliver medicine orders",
      roles: ["staff"], placement: "workspace", icon: Clipboard, group: "Pharmacy" },
  ],
};
