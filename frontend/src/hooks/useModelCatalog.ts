import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import { modelDisplayName } from "@/lib/modelNames";

export type CatalogStatus = "loading" | "ready" | "error";

/**
 * The model catalogue from GET /models (the only place the frontend fetches
 * it), plus the arena's model selection.
 *
 * The selection is seeded from the backend's `default_model` rather than a
 * hardcoded ID, which is how a previous default drifted onto a legacy model.
 */
export function useModelCatalog() {
  const [families, setFamilies] = useState<api.ModelFamily[]>([]);
  const [status, setStatus] = useState<CatalogStatus>("loading");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  // A ref as well, so long-lived socket handlers resolve names without
  // re-subscribing whenever the catalogue loads.
  const familiesRef = useRef<api.ModelFamily[]>([]);

  const load = useCallback(() => {
    return api
      .fetchModels()
      .then((data) => {
        familiesRef.current = data.families;
        setFamilies(data.families);
        setStatus("ready");
        if (data.default_model) {
          setSelectedModels((prev) => (prev.length ? prev : [data.default_model as string]));
        }
      })
      .catch(() => setStatus("error"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /** Refetch, e.g. after an API key is saved and a family becomes available. */
  const reloadModels = useCallback(() => {
    setStatus("loading");
    load();
  }, [load]);

  const modelLabel = useCallback((id: string) => modelDisplayName(id, familiesRef.current), []);
  const allModelIds = families.flatMap((f) => f.models.map((m) => m.id));

  return {
    families,
    status,
    reloadModels,
    selectedModels,
    setSelectedModels,
    allModelIds,
    modelLabel,
  };
}
