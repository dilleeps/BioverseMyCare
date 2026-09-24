import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Close } from "../../icons.jsx";
import PhotoFlow from "../../modules/photo-questions/PhotoFlow.jsx";
import { Camera } from "./icons.jsx";
import "./frontdoor.css";

// Camera button for the composer. Opens a sheet: choose what the photo is of, capture, preview, send.
// The first answer goes to `onResult(entry)`, which the front door shows as a card in the conversation.
export default function PhotoButton({ onResult, disabled }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const sheetRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab" && sheetRef.current) {
        const focusable = sheetRef.current.querySelectorAll("button, [href], input:not([tabindex='-1']), textarea, [tabindex='0']");
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function close() {
    setOpen(false);
    buttonRef.current?.focus();
  }

  return (
    <>
      <button ref={buttonRef} type="button" className="fd-icon-btn" onClick={() => setOpen(true)} disabled={disabled}
              aria-label="Ask with a photo" title="Ask with a photo" aria-haspopup="dialog">
        <Camera size={20} />
      </button>
      {open && createPortal(
        <div className="fd-sheet-backdrop" onClick={(e) => e.target === e.currentTarget && close()}>
          <div ref={sheetRef} className="fd-sheet" role="dialog" aria-modal="true" aria-label="Ask with a photo">
            <div className="row between fd-sheet-head">
              <span className="strong">Ask with a photo</span>
              <button type="button" className="fd-icon-btn plain" onClick={close} aria-label="Close"><Close size={18} /></button>
            </div>
            <PhotoFlow
              onCancel={close}
              onSent={(entry) => {
                onResult(entry);
                close();
              }}
            />
          </div>
        </div>,
        document.body, // outside the composer's <form>, so the sheet's own form isn't nested in it
      )}
    </>
  );
}
