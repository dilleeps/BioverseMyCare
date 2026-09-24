import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getUserId, setUserId } from "./api.js";

const SessionContext = createContext(null);

// Demo identity switcher. Replace with real sign-in (OIDC) before handling real data.
export function SessionProvider({ children }) {
  const [users, setUsers] = useState([]);
  const [me, setMe] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [error, setError] = useState(null);

  const loadMe = useCallback(async () => {
    try {
      setMe(await api("/me"));
      setStatus("ready");
    } catch (e) {
      setMe(null);
      setError(e);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const list = await api("/session/demo-users");
        setUsers(list);
        const stored = getUserId();
        const chosen = list.find((u) => u.id === stored) || list.find((u) => u.role === "patient") || list[0];
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

  return (
    <SessionContext.Provider value={{ users, me, status, error, switchTo }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  return useContext(SessionContext);
}
