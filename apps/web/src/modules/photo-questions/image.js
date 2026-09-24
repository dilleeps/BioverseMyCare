// Client-side checks that mirror the API (5 MB, JPEG/PNG/WebP, HEIC refused), so people learn at once.
export const MAX_BYTES = 5 * 1024 * 1024;
const ACCEPTED = ["image/jpeg", "image/png", "image/webp"];

export const HEIC_MESSAGE =
  "HEIC photos (the iPhone default) can't be read here yet. Take a screenshot of the photo and send that, " +
  "or set Camera > Formats to Most Compatible.";

export function checkFile(file) {
  if (!file) return "Choose a photo first.";
  const type = (file.type || "").toLowerCase();
  if (type.includes("heic") || type.includes("heif") || /\.(heic|heif)$/i.test(file.name || "")) return HEIC_MESSAGE;
  if (!ACCEPTED.includes(type)) return "Send a photo as a JPEG, PNG or WebP image.";
  if (file.size > MAX_BYTES) return "That photo is larger than 5 MB. Try a smaller photo, or crop it to what matters.";
  if (file.size === 0) return "That photo is empty. Try taking it again.";
  return null;
}

export function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("That photo couldn't be read. Try taking it again."));
    reader.readAsDataURL(file);
  });
}

export const KINDS = [
  { id: "medicine", label: "A medicine box or label", help: "I'll check it against your prescriptions." },
  { id: "skin", label: "A skin concern", help: "A rash, mole or spot. I won't diagnose it." },
  { id: "report", label: "A paper lab report", help: "I'll help you add it to your records." },
];

export const kindLabel = (id) => KINDS.find((k) => k.id === id)?.label || "Photo";
