import "./styles.css";
import Directory from "./Directory.jsx";
import ConsultRoom from "./ConsultRoom.jsx";
import ClinicianQueue from "./ClinicianQueue.jsx";
import ClinicianRoom from "./ClinicianRoom.jsx";
import VideoCall from "./VideoCall.jsx";
import ConsultsPanel from "./ConsultsPanel.jsx";
import { VideoIcon } from "./shared.jsx";

export default {
  id: "consult",
  title: "Online consults",
  group: "Care",
  order: 22,
  routes: [
    { path: "/consult", element: <Directory />, roles: ["patient"] },
    { path: "/consult/:consultId", element: <ConsultRoom />, roles: ["patient"] },
    { path: "/consult/:consultId/video", element: <VideoCall />, roles: ["patient"] },
    { path: "/clinician/consults", element: <ClinicianQueue />, roles: ["clinician"] },
    { path: "/clinician/consults/:consultId", element: <ClinicianRoom />, roles: ["clinician"] },
    { path: "/clinician/consults/:consultId/video", element: <VideoCall />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/consult", label: "See a doctor online", description: "Verified clinicians by message, video or phone",
      roles: ["patient"], placement: "hub" },
    { to: "/clinician/consults", label: "Online consults", description: "Requests, your specialty's queue and video calls",
      roles: ["clinician"], placement: "workspace", icon: VideoIcon, group: "Clinical" },
  ],
  workspacePanels: [{ id: "online-consults", title: "Online consults", order: 45, component: ConsultsPanel }],
};
