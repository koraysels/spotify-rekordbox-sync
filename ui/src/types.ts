export type Band = "accept" | "review" | "reject";

export interface SpotifyTrack {
  id: string;
  name: string;
  artists: string[];
  album: string;
  durationMs: number;
  isrc: string;
  url: string;
  display: string;
}

export interface Candidate {
  contentId: string;
  display: string;
  fileName: string;
  folderPath: string;
  lengthSeconds: number;
  bitRate: number;
  score: number;
  reason: string;
  titleScore: number;
  artistScore: number;
  durationScore: number;
}

export interface TrackPlan {
  track: SpotifyTrack;
  band: Band;
  contentId: string | null;
  score: number;
  reason: string;
  candidates: Candidate[];
}

export interface Coverage {
  matched: number;
  review: number;
  missing: number;
  total: number;
  percent: number;
}

export interface Playlist {
  id: string;
  name: string;
  trackCount: number;
  owner: string;
  snapshotId: string;
  selected?: boolean;
}

export interface PlaylistPlan {
  playlist: Playlist;
  tracks: TrackPlan[];
  toAdd: string[];
  toRemove: string[];
  coverage: Coverage;
}

export interface SyncPlan {
  playlists: PlaylistPlan[];
  coverage: Coverage;
}

export interface Status {
  db_path: string | null;
  rekordbox_running: boolean;
  tracks_indexed: number;
  authenticated: boolean;
  client_id_set: boolean;
  selected_playlists: string[];
}

export interface Settings {
  clientId: string;
  autoAccept: number;
  reject: number;
  allowRemovals: boolean;
}

export interface ApplyResult {
  playlistId: string;
  playlistName: string;
  added: number;
  removed: number;
  backupPath: string;
}

export interface Decision {
  spotify_id: string;
  content_id: string;
  accepted: boolean;
}
