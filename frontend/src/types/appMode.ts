/** Shared UI mode — single source of truth for live vs snapshot vs planned. */

export type AppMode = 'loading' | 'live' | 'verified_snapshot' | 'planned';

/** Badge/display mode for data source labels on report and processing pages. */
export type DataSourceMode = 'live' | 'verified_snapshot' | 'planned' | 'loading';

export interface DatabaseTarget {
  host: string;
  port: number;
  database: string;
}

export interface AppModeState {
  /** Resolved application mode for processing-capable pages. */
  mode: AppMode;
  /** HTTP API reachable (any /health response, including 503 degraded). */
  backendReachable: boolean;
  /** Postgres probe succeeded per /health. */
  databaseOk: boolean;
  /** Human-readable reason for the current mode. */
  reason: string;
  /** True when POST /runs and live validation are allowed. */
  canRunValidation: boolean;
  /** Badge label mode — never "live" unless backend+DB healthy. */
  displayMode: DataSourceMode;
  databaseTarget?: DatabaseTarget;
  isResolved: boolean;
}

export const MODE_LABELS: Record<Exclude<DataSourceMode, 'loading'>, string> = {
  live: 'Live API',
  verified_snapshot: 'Verified Snapshot',
  planned: 'Planned',
};

export const SNAPSHOT_MODE_MESSAGE =
  'Using a verified backend-generated report snapshot for this walkthrough. Live validation is unavailable in this environment.';
