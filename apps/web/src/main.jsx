import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import { SessionProvider } from "./session.jsx";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

// The service worker (public/sw.js) makes the app installable, shows an offline page and receives push
// notifications. Production builds only: in development it would cache files the dev server changes.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      // Not fatal: the app works without it, just without offline page and background push.
    });
  });
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data?.type === "bioverse:push") window.dispatchEvent(new Event("bioverse:notifications"));
    if (e.data?.type === "bioverse:navigate" && typeof e.data.link === "string" && e.data.link.startsWith("/")
        && !e.data.link.startsWith("//")) {
      window.location.assign(e.data.link);
    }
  });
}
