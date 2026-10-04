/** Shared presentational pieces: tones, empty/error states, bounded lists. */

import type { ReactNode } from "react";
import type { Tone } from "../format";
import { ApiRequestError, OfflineError } from "../api";

export function Badge({ tone, children }: { readonly tone: Tone; readonly children: ReactNode }) {
  return <span className={`badge badge--${tone}`}>{children}</span>;
}

export function Empty({ title, detail }: { readonly title: string; readonly detail: string }) {
  return (
    <div className="state state--empty" role="status">
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}

export function Loading({ label }: { readonly label: string }) {
  return (
    <div className="state state--loading" role="status" aria-live="polite">
      {label}…
    </div>
  );
}

/** Render a failure without leaking a stack trace or an internal path. */
export function Failure({ error, onRetry }: { readonly error: unknown; readonly onRetry: () => void }) {
  if (error instanceof OfflineError) {
    return (
      <div className="state state--error" role="alert">
        <h3>Local API unreachable</h3>
        <p>
          The workbench could not reach the local server. Confirm <code>researchos web serve</code> is still
          running, then retry.
        </p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  if (error instanceof ApiRequestError) {
    return (
      <div className="state state--error" role="alert">
        <h3>Request refused</h3>
        <p>
          <code>{error.code}</code>: {error.message}
        </p>
        <button type="button" onClick={onRetry}>
          Retry
        </button>
      </div>
    );
  }
  return (
    <div className="state state--error" role="alert">
      <h3>Unexpected failure</h3>
      <p>The view could not be rendered. Reload to try again.</p>
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

export interface BoundedListProps<T> {
  readonly items: ReadonlyArray<T>;
  readonly cap: number;
  readonly totalLabel: string;
  readonly row: (item: T, index: number) => ReactNode;
}

/** Render at most `cap` rows and say plainly how many were withheld.
 *
 * A long event history must not be rendered in full: the point of the bound is
 * that the page stays responsive, and silently truncating would misreport the
 * contents.
 */
export function BoundedList<T>({ items, cap, totalLabel, row }: BoundedListProps<T>) {
  const shown = items.slice(0, cap);
  const withheld = items.length - shown.length;
  return (
    <div>
      <table>
        <caption className="visually-hidden">{totalLabel}</caption>
        <tbody>{shown.map((item, index) => row(item, index))}</tbody>
      </table>
      {withheld > 0 ? (
        <p className="note">
          Showing {shown.length} of {items.length} {totalLabel}. Narrow the filter or page with the cursor to
          see the rest.
        </p>
      ) : null}
    </div>
  );
}

export function KeyValue({ items }: { readonly items: ReadonlyArray<readonly [string, ReactNode]> }) {
  return (
    <dl className="kv">
      {items.map(([key, value]) => (
        <div key={key} className="kv__row">
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Code({ children }: { readonly children: string }) {
  return (
    <pre className="code" tabIndex={0} aria-label="Document contents">
      {children}
    </pre>
  );
}
