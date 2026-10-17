import { useState } from "react";
import { api } from "../api";

interface Props {
  sourceId: string | null | undefined;
  onRefreshed: () => void;
}

export function OfficialStatus({ sourceId, onRefreshed }: Props) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const provider =
    sourceId === "official.openai"
      ? "openai"
      : sourceId === "official.claude"
        ? "claude"
        : null;
  if (!provider) return null;
  const label = provider === "openai" ? "OpenAI" : "Claude";
  return (
    <section
      className="map-official-status"
      aria-label={`${label} official status source`}
    >
      <h3>{label} public status page</h3>
      <p>
        Refresh the official aggregate report. Your own account, region and
        request health may differ. Reports become stale after five minutes.
      </p>
      <button
        type="button"
        className="map-primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setMessage("");
          try {
            await api.refreshProvider(provider);
            onRefreshed();
            setMessage("Official report refreshed. No model API was called.");
          } catch (error) {
            setMessage(
              error instanceof Error
                ? error.message
                : "Refresh failed. The previous report remains unchanged.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Refreshing official report…" : `Refresh ${label} status`}
      </button>
      <p>
        <a
          href={
            provider === "openai"
              ? "https://status.openai.com/"
              : "https://status.claude.com/"
          }
          target="_blank"
          rel="noreferrer"
        >
          Open official status page ↗
        </a>
      </p>
      {message && <p role="status">{message}</p>}
    </section>
  );
}
