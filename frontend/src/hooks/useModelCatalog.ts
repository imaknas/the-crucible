import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import { modelDisplayName } from "@/lib/modelNames";
import { parseStoredSelection, resolveSelection, type SelectionDefaults } from "@/lib/modelSelection";
import { useStoredValue, writeStoredValue } from "@/hooks/useStoredValue";
import { FALLBACK_LIMITS, catalogColor, resolveLimits, type Limits } from "@/lib/catalog";

export type CatalogStatus = "loading" | "ready" | "error";

const SELECTION_KEY = "crucible_selected_models";

/**
 * The model catalogue from GET /models (the only place the frontend fetches
 * it), plus the arena's model selection.
 *
 * The selection persists, and starts from the backend's `default_arena_models`
 * (see `resolveSelection`) rather than a hardcoded ID, which is how a previous
 * default drifted onto a legacy model.
 */
export function useModelCatalog() {
  const [families, setFamilies] = useState<api.ModelFamily[]>([]);
  const [status, setStatus] = useState<CatalogStatus>("loading");
  const [defaults, setDefaults] = useState<SelectionDefaults>({});
  // The summarizer the backend uses when none is chosen, for the keys that are set.
  const [defaultSummarizer, setDefaultSummarizer] = useState<string | null>(null);
  // What the backend enforces (prompt and system prompt length, debate
  // rounds); these replace the frontend's copies once loaded.
  const [limits, setLimits] = useState<Limits>(FALLBACK_LIMITS);
  const stored = useStoredValue(SELECTION_KEY);

  const load = useCallback(() => {
    return api
      .fetchModels()
      .then((data) => {
        setFamilies(data.families);
        setStatus("ready");
        setDefaultSummarizer(data.default_summarizer ?? null);
        setLimits(resolveLimits(data.limits));
        setDefaults({ default_model: data.default_model, default_arena_models: data.default_arena_models });
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

  const selectedModels = useMemo(
    () => resolveSelection(parseStoredSelection(stored), families, defaults),
    [stored, families, defaults],
  );
  const setSelectedModels = useCallback(
    (models: string[]) => writeStoredValue(SELECTION_KEY, JSON.stringify(models)),
    [],
  );

  // Changes identity once the catalogue loads, so memoised views that show
  // names re-render with them. Socket handlers read it through a ref.
  const modelLabel = useCallback((id: string) => modelDisplayName(id, families), [families]);
  // The family colour the backend ships; guessed from the id until it loads.
  const modelColor = useCallback((id: string) => catalogColor(id, families), [families]);
  const allModelIds = families.flatMap((f) => f.models.map((m) => m.id));
  // Models whose family has a key: the ones a synthesizer can be picked from.
  const availableModelIds = families.filter((f) => f.available).flatMap((f) => f.models.map((m) => m.id));

  return {
    families,
    status,
    reloadModels,
    selectedModels,
    setSelectedModels,
    allModelIds,
    availableModelIds,
    modelLabel,
    modelColor,
    defaultSummarizer,
    limits,
  };
}
