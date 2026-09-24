import "./styles.css";
import { Camera } from "../../components/frontdoor/icons.jsx";
import PhotoAsk from "./PhotoAsk.jsx";
import { SkinPhotoDetail, SkinPhotoList } from "./SkinPhotos.jsx";

export default {
  id: "photo-questions",
  title: "Ask with a photo",
  group: "Care",
  order: 35,
  routes: [
    { path: "/ask/photo", element: <PhotoAsk />, roles: ["patient"] },
    { path: "/clinician/skin-photos", element: <SkinPhotoList />, roles: ["clinician"] },
    { path: "/clinician/skin-photos/:id", element: <SkinPhotoDetail />, roles: ["clinician"] },
  ],
  nav: [
    { to: "/ask/photo", label: "Ask with a photo", description: "A medicine box, a skin concern or a paper lab report",
      roles: ["patient"], placement: "hub" },
    { to: "/clinician/skin-photos", label: "Patient photos", description: "Skin photos patients sent with a note",
      roles: ["clinician"], placement: "workspace", icon: Camera, group: "Clinical" },
  ],
};
