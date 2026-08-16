import { useEffect, useState } from "react";
import type { PageId } from "../api/types";

const pages = new Set<PageId>(["control", "devices", "settings"]);

function readHash(): PageId {
  const value = window.location.hash.slice(1) as PageId;
  return pages.has(value) ? value : "control";
}

export function useHashPage() {
  const [page, setPageState] = useState<PageId>(readHash);

  useEffect(() => {
    const onHashChange = () => setPageState(readHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setPage = (next: PageId) => {
    window.location.hash = next;
    setPageState(next);
  };

  return [page, setPage] as const;
}
