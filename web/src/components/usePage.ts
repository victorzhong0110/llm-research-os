/** Bounded page loading with cancellation and an explicit retry. */

import { useCallback, useEffect, useState } from "react";
import type { Paged } from "../api";

export interface PageState<T> {
  readonly page: Paged<T> | null;
  readonly error: unknown;
  readonly reload: () => void;
}

/** Load one cursor-addressed page.
 *
 * A component unmounting, or switching cursor, must not let a late response
 * paint over the newer view, so the effect marks itself dead on cleanup.
 */
export function usePage<T>(
  load: (cursor: string | null) => Promise<Paged<T>>,
  cursor: string | null,
): PageState<T> {
  const [page, setPage] = useState<Paged<T> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    setPage(null);
    setError(null);
    load(cursor).then(
      (result) => {
        if (live) {
          setPage(result);
        }
      },
      (failure: unknown) => {
        if (live) {
          setError(failure);
        }
      },
    );
    return () => {
      live = false;
    };
  }, [cursor, load, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { page, error, reload };
}
