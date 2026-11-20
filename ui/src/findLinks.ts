import { searchQueryFor } from "./clipboard";
import type { TrackPlan } from "./types";

const LOWQ = /\blowq\b/i;

/** A matched row whose best file is one rbsync fetched from a lossy source. */
export function isLowq(row: TrackPlan): boolean {
  const best = row.candidates[0];
  return row.band !== "reject" && !!best && LOWQ.test(best.comment ?? "");
}

export interface FindLink {
  label: string;
  url: string;
}

/** Shops and catalogues to look a track up in, in the order they are offered. */
export function findLinks(track: { artists: string[]; name: string }): FindLink[] {
  const q = encodeURIComponent(searchQueryFor(track));
  return [
    { label: "Beatport", url: `https://www.beatport.com/search?q=${q}` },
    { label: "Bandcamp", url: `https://bandcamp.com/search?q=${q}&item_type=t` },
    { label: "Traxsource", url: `https://www.traxsource.com/search?term=${q}` },
    { label: "Juno Download", url: `https://www.junodownload.com/search/?q%5Ball%5D%5B%5D=${q}` },
    { label: "Discogs", url: `https://www.discogs.com/search/?q=${q}&type=all` },
  ];
}
