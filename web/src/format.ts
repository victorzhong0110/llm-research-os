/** Presentation rules for run state and data origin.
 *
 * The R10 acceptance bar is that `unknown`, `lost`, `failed`,
 * `cancel-requested` and an observed stop are distinguishable and never carry
 * success styling. A cancellation request is a *request*, not an outcome, and
 * a run that is not observed is not a failure. Each state therefore gets its
 * own tone, label and explanation rather than a boolean.
 */

import type { RunItem } from "./generated/local-api";

export type Tone = "neutral" | "progress" | "success" | "warning" | "danger" | "unknown";

export interface Presentation {
  readonly label: string;
  readonly tone: Tone;
  readonly detail: string;
}

/** The generated field is optional, so the closed state set excludes undefined. */
export type ObservationState = NonNullable<RunItem["observation"]>;

/** Tones that may be described as a positive outcome. Nothing else qualifies. */
const SUCCESSFUL: ReadonlySet<ObservationState> = new Set(["succeeded"]);

const PRESENTATION: Readonly<Record<ObservationState, Presentation>> = {
  succeeded: {
    label: "Succeeded",
    tone: "success",
    detail: "A completed outcome was observed and recorded.",
  },
  running: {
    label: "Running",
    tone: "progress",
    detail: "The run started and has not reported a terminal outcome.",
  },
  queued: {
    label: "Queued",
    tone: "neutral",
    detail: "The run is recorded but has not started.",
  },
  "cancel-requested": {
    label: "Cancellation requested",
    tone: "warning",
    detail: "A cancellation was requested. This is not an observed stop.",
  },
  "observed-stop": {
    label: "Stopped (observed)",
    tone: "warning",
    detail: "The process was observed to stop. It did not report success.",
  },
  failed: {
    label: "Failed",
    tone: "danger",
    detail: "A terminal failure was recorded.",
  },
  lost: {
    label: "Lost",
    tone: "unknown",
    detail: "The result could not be recovered. It is neither success nor failure.",
  },
  unknown: {
    label: "Unknown",
    tone: "unknown",
    detail: "The outcome was never observed. It must not be reported as success or failure.",
  },
  absent: {
    label: "No lifecycle facts",
    tone: "neutral",
    detail: "This run has no lifecycle events in the current page, so no state is claimed.",
  },
};

export function presentObservation(observation: ObservationState | undefined): Presentation {
  return PRESENTATION[observation ?? "absent"];
}

/** True only for an observed, successful terminal outcome. */
export function isSuccessful(observation: ObservationState | undefined): boolean {
  return observation !== undefined && SUCCESSFUL.has(observation);
}

/** A value that is not observed cannot be compared or summarised as a result. */
export function isReportableOutcome(observation: ObservationState | undefined): boolean {
  const state = observation ?? "absent";
  return state === "succeeded" || state === "failed" || state === "observed-stop";
}

export function presentOrigin(origin: RunItem["origin"] | undefined): string {
  switch (origin) {
    case "real":
      return "Measured";
    case "synthetic":
      return "Synthetic (not a measurement)";
    case "absent":
    default:
      return "No data";
  }
}

export function originTone(origin: RunItem["origin"] | undefined): Tone {
  return origin === "real" ? "success" : origin === "synthetic" ? "warning" : "neutral";
}

/** Shorten a digest for display without losing its identity for copy/paste. */
export function shortDigest(digest: string, keep = 12): string {
  const [algorithm, hex] = digest.split(":");
  if (hex === undefined || hex.length <= keep * 2) {
    return digest;
  }
  return `${algorithm}:${hex.slice(0, keep)}…${hex.slice(-4)}`;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

/** Render an ISO timestamp, keeping the raw value available for the title. */
export function formatTime(value: string): string {
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? value : new Date(parsed).toISOString().replace("T", " ").slice(0, 19);
}
