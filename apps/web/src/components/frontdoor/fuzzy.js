// Simple fuzzy matching for the hub search: every word typed (or spoken) must match a word in the entry's
// label or description, by prefix, substring, one small typo, or letters in order. Label hits rank highest.

const words = (s) => (s || "").toLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}\s]/gu, " ").split(/\s+/).filter(Boolean);

// Filler that people say to a voice search ("open my bills please").
const FILLER = new Set(["a", "an", "the", "my", "me", "i", "to", "go", "open", "show", "please", "want", "find", "for", "of", "see"]);

function withinOneEdit(a, b) {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i += 1;
      j += 1;
      continue;
    }
    edits += 1;
    if (edits > 1) return false;
    if (a.length > b.length) i += 1;
    else if (b.length > a.length) j += 1;
    else {
      i += 1;
      j += 1;
    }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

function subsequence(q, w) {
  let i = 0;
  for (const ch of w) if (ch === q[i]) i += 1;
  return i === q.length;
}

function termScore(term, fieldWords) {
  let best = 0;
  for (const w of fieldWords) {
    if (w === term) best = Math.max(best, 10);
    else if (w.startsWith(term)) best = Math.max(best, 8);
    else if (term.length >= 3 && w.includes(term)) best = Math.max(best, 5);
    // One typo, in the whole word or in the part typed so far ("refils" -> "refills", "apointm" -> "appointments").
    else if (term.length >= 4 && (withinOneEdit(term, w) || withinOneEdit(term, w.slice(0, term.length)))) {
      best = Math.max(best, 4);
    }
    else if (term.length >= 3 && w[0] === term[0] && subsequence(term, w)) best = Math.max(best, 2);
  }
  return best;
}

export function scoreEntry(query, entry) {
  const all = words(query);
  const terms = all.filter((t) => !FILLER.has(t));
  const use = terms.length ? terms : all;
  if (!use.length) return 0;
  const label = words(entry.label);
  const desc = words(`${entry.description || ""} ${entry.group || ""}`);
  let total = 0;
  for (const t of use) {
    const s = Math.max(termScore(t, label) * 2, termScore(t, desc));
    if (s === 0) return 0; // every word must match somewhere
    total += s;
  }
  return total;
}

export function search(query, entries, limit = 8) {
  return entries
    .map((e) => ({ e, s: scoreEntry(query, e) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || a.e.label.localeCompare(b.e.label))
    .slice(0, limit)
    .map((x) => x.e);
}
