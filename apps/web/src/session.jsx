import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, getUserId, setUserId } from "./api.js";

const SessionContext = createContext(null);

// Who is signed in. Single sign-on (Microsoft Entra ID, Okta, Google) uses a secure cookie set by the API;
// the demo identity switcher is offered only when the API allows demo sign-in.
export function SessionProvider({ children }) {
  const [config, setConfig] = useState(null);
  const [users, setUsers] = useState([]);
  const [me, setMe] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | signed_out | error
  const [error, setError] = useState(null);

  const loadMe = useCallback(async () => {
    try {
      setMe(await api("/me"));
      setStatus("ready");
    } catch (e) {
      setMe(null);
      if (e instanceof ApiError && e.status === 401) {
        setStatus("signed_out");
      } else {
        setError(e);
        setStatus("error");
      }
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const cfg = await api("/auth/config");
        setConfig(cfg);
        if (!cfg.demo) setUserId(null);
        // A single sign-on session wins over a remembered demo identity.
        const saved = getUserId();
        if (cfg.providers.length > 0) {
          setUserId(null);
          try {
            const current = await api("/me");
            if (current.auth === "sso") {
              setMe(current);
              setStatus("ready");
              return;
            }
          } catch {
            // not signed in with SSO
          }
        }
        if (!cfg.demo) {
          setStatus("signed_out");
          return;
        }
        const list = await api("/session/demo-users");
        setUsers(list);
        const chosen = list.find((u) => u.id === saved) || list.find((u) => u.role === "patient") || list[0];
        if (!chosen) throw new Error("No demo users. Run the database seed.");
        setUserId(chosen.id);
        await loadMe();
      } catch (e) {
        setError(e);
        setStatus("error");
      }
    })();
  }, [loadMe]);

  const switchTo = useCallback(
    async (id) => {
      setUserId(id);
      setStatus("loading");
      await loadMe();
    },
    [loadMe],
  );

  const signOut = useCallback(async () => {
    setUserId(null);
    let redirect = "/signin";
    try {
      redirect = (await api("/auth/logout", { method: "POST" })).redirect || redirect;
    } catch {
      // the session is gone either way
    }
    window.location.assign(redirect);
  }, []);

  return (
    <SessionContext.Provider value={{ config, users, me, status, error, switchTo, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  return useContext(SessionContext);
}
