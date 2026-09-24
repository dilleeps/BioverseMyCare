import { useEffect, useState } from "react";
import { getUserId } from "../../api.js";

// An <img> for an API path that needs the signed-in identity header (a plain src can't send it).
export default function AuthImage({ path, alt, className }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let revoked = false;
    let objectUrl = null;
    setFailed(false);
    fetch(`/api${path}`, { headers: { "X-Bioverse-User": getUserId() || "" } })
      .then((res) => (res.ok ? res.blob() : Promise.reject(new Error(String(res.status)))))
      .then((blob) => {
        if (revoked) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => !revoked && setFailed(true));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [path]);
  if (failed) return <div className={`${className || ""} photo-missing`}>The photo couldn't be loaded.</div>;
  if (!url) return <div className={`${className || ""} skeleton photo-loading`} aria-label="Loading photo" />;
  return <img src={url} alt={alt} className={className} />;
}
