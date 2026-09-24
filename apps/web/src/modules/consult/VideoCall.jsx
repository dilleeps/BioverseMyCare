import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, getUserId } from "../../api.js";
import { useSession } from "../../session.jsx";
import { fmtDateTime } from "../../format.js";
import { Back, Warning } from "../../icons.jsx";
import { ChatIcon, LeaveIcon, MicIcon, MicOffIcon, useConsult, VideoIcon, VideoOffIcon } from "./shared.jsx";

// 1:1 WebRTC call. Media goes peer to peer; the API only relays the signaling (offer, answer, ICE candidates),
// which each side polls. The clinician always makes the offer, so the two sides never offer at once.
// Every offer carries a generation number; candidates are tagged with it so stale ones are ignored.

const POLL_FAST = 800;
const POLL_SLOW = 2000;

function supported() {
  return Boolean(navigator.mediaDevices?.getUserMedia && window.RTCPeerConnection);
}

function sendLeaveOnUnload(consultId) {
  // keepalive lets the request finish while the page closes; sendBeacon can't carry our identity header.
  try {
    fetch(`/api/consultations/${consultId}/signals`, {
      method: "POST", keepalive: true,
      headers: { "Content-Type": "application/json", "X-Bioverse-User": getUserId() || "" },
      body: JSON.stringify({ kind: "leave" }),
    });
  } catch {
    // Nothing to do: the other side will see the connection drop.
  }
}

export default function VideoCall() {
  const { consultId } = useParams();
  const { me } = useSession();
  const navigate = useNavigate();
  const { data: c, error } = useConsult(consultId, 15000);
  const back = me.role === "clinician" ? `/clinician/consults/${consultId}` : `/consult/${consultId}`;
  const offerer = me.role === "clinician";

  const [phase, setPhase] = useState(supported() ? "starting" : "unsupported");
  const [problem, setProblem] = useState(null);
  const [audioOnly, setAudioOnly] = useState(false);
  const [micOn, setMicOn] = useState(true);
  const [camOn, setCamOn] = useState(true);
  const [peerHere, setPeerHere] = useState(false);
  const [connected, setConnected] = useState(false);

  const localRef = useRef(null);
  const remoteRef = useRef(null);
  const stream = useRef(null);
  const call = useRef({ pc: null, gen: 0, pending: {}, stop: true, cursor: 0, ice: [], chain: Promise.resolve(), joined: false });

  // --- Camera and microphone ---------------------------------------------------------------
  const startMedia = useCallback(async () => {
    if (!supported()) { setPhase("unsupported"); return; }
    setPhase("starting");
    setProblem(null);
    try {
      let s;
      try {
        s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      } catch (e) {
        if (e.name !== "NotFoundError" && e.name !== "OverconstrainedError" && e.name !== "NotReadableError") throw e;
        s = await navigator.mediaDevices.getUserMedia({ audio: true }); // no usable camera: audio only
        setAudioOnly(true);
      }
      stream.current = s;
      if (localRef.current) localRef.current.srcObject = s;
      setPhase("preview");
    } catch (e) {
      setPhase(e.name === "NotAllowedError" || e.name === "SecurityError" ? "denied" : "nodevice");
      setProblem(e.message);
    }
  }, []);

  useEffect(() => {
    if (supported()) startMedia();
    return () => stream.current?.getTracks().forEach((t) => t.stop());
  }, [startMedia]);

  useEffect(() => {
    if (localRef.current && stream.current) localRef.current.srcObject = stream.current;
  }, [phase]);

  function toggleMic() {
    const on = !micOn;
    stream.current?.getAudioTracks().forEach((t) => { t.enabled = on; });
    setMicOn(on);
  }
  function toggleCam() {
    const on = !camOn;
    stream.current?.getVideoTracks().forEach((t) => { t.enabled = on; });
    setCamOn(on);
  }

  // --- Signaling -----------------------------------------------------------------------------
  const send = useCallback((kind, payload) => {
    const st = call.current;
    st.chain = st.chain.then(() => api(`/consultations/${consultId}/signals`, { method: "POST", body: { kind, payload } }))
      .catch(() => {});
    return st.chain;
  }, [consultId]);

  const closePeer = useCallback(() => {
    const st = call.current;
    if (st.pc) {
      st.pc.onicecandidate = null;
      st.pc.ontrack = null;
      st.pc.onconnectionstatechange = null;
      st.pc.close();
    }
    st.pc = null;
    if (remoteRef.current) remoteRef.current.srcObject = null;
    setConnected(false);
  }, []);

  const newPeer = useCallback((gen) => {
    closePeer();
    const st = call.current;
    const pc = new RTCPeerConnection({ iceServers: st.ice });
    st.pc = pc;
    st.gen = gen;
    stream.current?.getTracks().forEach((t) => pc.addTrack(t, stream.current));
    pc.onicecandidate = (e) => { if (e.candidate) send("ice", { gen, candidate: e.candidate.toJSON() }); };
    pc.ontrack = (e) => { if (remoteRef.current) remoteRef.current.srcObject = e.streams[0]; };
    pc.onconnectionstatechange = () => {
      if (pc !== call.current.pc) return;
      if (pc.connectionState === "connected") setConnected(true);
      if (["failed", "disconnected", "closed"].includes(pc.connectionState)) setConnected(false);
    };
    return pc;
  }, [closePeer, send]);

  const flushIce = useCallback(async (pc, gen) => {
    const st = call.current;
    for (const cand of st.pending[gen] || []) {
      try { await pc.addIceCandidate(cand); } catch { /* stale candidate */ }
    }
    delete st.pending[gen];
  }, []);

  const makeOffer = useCallback(async () => {
    const gen = Date.now();
    const pc = newPeer(gen);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await send("offer", { gen, type: offer.type, sdp: offer.sdp });
  }, [newPeer, send]);

  const handle = useCallback(async (sig) => {
    const st = call.current;
    const p = sig.payload || {};
    if (sig.kind === "join") {
      setPeerHere(true);
      if (offerer) await makeOffer();
    } else if (sig.kind === "leave") {
      setPeerHere(false);
      closePeer();
      st.pending = {};
    } else if (sig.kind === "offer" && !offerer) {
      setPeerHere(true);
      const pc = newPeer(p.gen);
      await pc.setRemoteDescription({ type: "offer", sdp: p.sdp });
      await flushIce(pc, p.gen);
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await send("answer", { gen: p.gen, type: answer.type, sdp: answer.sdp });
    } else if (sig.kind === "answer" && offerer) {
      if (st.pc && p.gen === st.gen && st.pc.signalingState === "have-local-offer") {
        await st.pc.setRemoteDescription({ type: "answer", sdp: p.sdp });
        await flushIce(st.pc, p.gen);
      }
    } else if (sig.kind === "ice") {
      if (st.pc && p.gen === st.gen && st.pc.remoteDescription) {
        try { await st.pc.addIceCandidate(p.candidate); } catch { /* stale candidate */ }
      } else if (!st.gen || p.gen >= st.gen) {
        (st.pending[p.gen] ||= []).push(p.candidate);
      }
    }
  }, [offerer, makeOffer, closePeer, newPeer, flushIce, send]);

  const poll = useCallback(async () => {
    const st = call.current;
    if (st.stop) return;
    let delay = POLL_FAST;
    try {
      const r = await api(`/consultations/${consultId}/signals?after=${st.cursor}`);
      st.cursor = r.cursor;
      setPeerHere(r.peer_present);
      for (const sig of r.signals) await handle(sig);
      if (st.pc?.connectionState === "connected") delay = POLL_SLOW;
    } catch (e) {
      if (e.status === 409 || e.status === 404) {
        st.stop = true;
        closePeer();
        setPhase("ended");
        return;
      }
      delay = POLL_SLOW;
    }
    if (!st.stop) setTimeout(poll, delay);
  }, [consultId, handle, closePeer]);

  async function join() {
    const st = call.current;
    setPhase("joining");
    try {
      const cfg = await api("/consultations/rtc-config");
      st.ice = cfg.ice_servers;
      const first = await api(`/consultations/${consultId}/signals`);
      st.cursor = first.cursor;
      st.stop = false;
      st.joined = true;
      await send("join");
      setPhase("in_call");
      setPeerHere(first.peer_present);
      if (offerer && first.peer_present) await makeOffer();
      setTimeout(poll, POLL_FAST);
    } catch (e) {
      setProblem(e.message);
      setPhase("preview");
    }
  }

  const leave = useCallback(async (to) => {
    const st = call.current;
    st.stop = true;
    closePeer();
    if (st.joined) await send("leave");
    st.joined = false;
    stream.current?.getTracks().forEach((t) => t.stop());
    navigate(to || back);
  }, [closePeer, send, navigate, back]);

  useEffect(() => {
    const onUnload = () => { if (call.current.joined) sendLeaveOnUnload(consultId); };
    window.addEventListener("pagehide", onUnload);
    return () => {
      window.removeEventListener("pagehide", onUnload);
      const st = call.current;
      if (st.joined) sendLeaveOnUnload(consultId);
      st.stop = true;
      st.joined = false;
      closePeer();
    };
  }, [consultId, closePeer]);

  useEffect(() => { document.title = "Video call · Bioverse"; }, []);

  async function switchToMessages(why) {
    try {
      await api(`/consultations/${consultId}/switch-to-message`, { method: "POST", body: { why } });
    } catch {
      // Already switched, or closed: the consult page explains.
    }
    stream.current?.getTracks().forEach((t) => t.stop());
    navigate(back);
  }

  const other = me.role === "clinician" ? c?.patient?.name : c?.practitioner?.name;

  if (error && !c) {
    return <main className="column"><div className="error-box">{error.status === 404 ? "We couldn't find that consult." : error.message}</div></main>;
  }

  const fallback = (title, body, retry) => (
    <div className="call-fallback card stack" role="alert">
      <div className="row strong"><Warning size={18} /> {title}</div>
      <p className="small">{body}</p>
      <div className="row wrap" style={{ gap: 8 }}>
        {retry && <button className="btn" onClick={startMedia}>Try again</button>}
        <button className="btn primary" onClick={() => switchToMessages(title)}><ChatIcon /> Continue by message instead</button>
      </div>
    </div>
  );

  return (
    <main className="call-page" aria-label="Video call">
      <div className="call-head">
        <Link to={back} className="btn ghost sm call-back" onClick={(e) => { e.preventDefault(); leave(); }}><Back size={16} /> Back to consult</Link>
        <div className="stack" style={{ gap: 0, minWidth: 0 }}>
          <h1 className="call-title">{other ? `Video call with ${other}` : "Video call"}</h1>
          {c?.scheduled_at && <span className="tiny">Scheduled {fmtDateTime(c.scheduled_at)}</span>}
        </div>
      </div>

      {phase === "unsupported" && fallback("This browser can't make video calls",
        "Your browser doesn't support camera calls here. Try a current version of Chrome, Edge, Firefox or Safari, or carry on by secure message.")}
      {phase === "denied" && fallback("Camera and microphone are blocked",
        "Bioverse needs permission to use your camera and microphone. Allow them in your browser's address bar, then try again.", true)}
      {phase === "nodevice" && fallback("No camera or microphone found",
        "We couldn't start a camera or microphone on this device. Check they're connected and not used by another app.", true)}
      {phase === "ended" && (
        <div className="call-fallback card stack" role="status">
          <div className="strong">This call has ended</div>
          <p className="small">The consult is no longer open for video.</p>
          <Link className="btn primary" to={back}>Back to the consult</Link>
        </div>
      )}

      {["starting", "preview", "joining", "in_call"].includes(phase) && (
        <>
          <div className="call-stage">
            <div className="call-remote">
              <video ref={remoteRef} autoPlay playsInline aria-label={other ? `${other}'s video` : "Other person's video"} />
              {!connected && (
                <div className="call-wait">
                  {phase === "in_call"
                    ? (peerHere ? "Connecting..." : `Waiting for ${other || "the other person"} to join`)
                    : phase === "starting" ? "Starting your camera..." : "Check your camera and microphone, then join."}
                </div>
              )}
            </div>
            <div className={`call-local ${camOn && !audioOnly ? "" : "off"}`}>
              <video ref={localRef} autoPlay playsInline muted aria-label="Your camera preview" />
              {(!camOn || audioOnly) && <span className="tiny">{audioOnly ? "Audio only" : "Camera off"}</span>}
            </div>
          </div>
          {problem && <div className="error-box small">{problem}</div>}
          <div className="call-controls" role="toolbar" aria-label="Call controls">
            <button className={`call-btn ${micOn ? "" : "off"}`} onClick={toggleMic} aria-pressed={!micOn} disabled={phase === "starting"}>
              {micOn ? <MicIcon size={22} /> : <MicOffIcon size={22} />}<span>{micOn ? "Mute" : "Unmute"}</span>
            </button>
            <button className={`call-btn ${camOn ? "" : "off"}`} onClick={toggleCam} aria-pressed={!camOn} disabled={phase === "starting" || audioOnly}>
              {camOn ? <VideoIcon size={22} /> : <VideoOffIcon size={22} />}<span>{camOn ? "Camera off" : "Camera on"}</span>
            </button>
            {phase === "in_call" ? (
              <button className="call-btn leave" onClick={() => leave()}><LeaveIcon size={22} /><span>Leave</span></button>
            ) : (
              <button className="call-btn join" onClick={join} disabled={phase !== "preview" || !c}><VideoIcon size={22} /><span>Join call</span></button>
            )}
          </div>
          <p className="tiny call-note">
            Video goes directly between your device and theirs. If it won't connect,{" "}
            <button className="linkish" onClick={() => switchToMessages("Video would not connect")}>switch to secure messages</button>.
          </p>
        </>
      )}
    </main>
  );
}
