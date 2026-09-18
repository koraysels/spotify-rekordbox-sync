// Camelot notation for Spotify's key (0..11, C = 0) and mode (1 major, 0 minor).
// The core adds "camelot" to features; this covers features cached before it did.
const MAJOR = ["8B", "3B", "10B", "5B", "12B", "7B", "2B", "9B", "4B", "11B", "6B", "1B"];
const MINOR = ["5A", "12A", "7A", "2A", "9A", "4A", "11A", "6A", "1A", "8A", "3A", "10A"];

export function camelotOf(features?: {
  camelot?: string;
  key: number | null;
  mode: number | null;
}): string {
  if (!features) return "";
  if (features.camelot) return features.camelot;
  const { key, mode } = features;
  if (key === null || mode === null || key < 0 || key > 11) return "";
  return (mode === 1 ? MAJOR : MINOR)[key];
}
