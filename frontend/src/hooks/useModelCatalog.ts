import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import { modelDisplayName } from "@/lib/modelNames";

/**
 * The model catalogue from GET /models, plus the arena's model selection.
 *
 * The selection is seeded from the backend's `default_model` rather than a
 * hardcoded ID, which is how a previous default drifted onto a legacy model.
 */
export function useModelCatalog() {
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [allModelIds, setAllModelIds] = useState<string[]>([]);
  // A ref as well, so long-lived socket handlers resolve names without
  // re-subscribing whenever the catalogue loads.
  const familiesRef = useRef<api.ModelFamily[]>([]);

  useEffect(() => {
    api
      .fetchModels()
      .then((data) => {
        familiesRef.current = data.families;
        setAllModelIds(data.families.flatMap((f) => f.models.map((m) => m.id)));
        if (data.default_model) {
          setSelectedModels((prev) => (prev.length ? prev : [data.default_model as string]));
        }
      })
      .catch(() => {});
  }, []);

  const modelLabel = useCallback((id: string) => modelDisplayName(id, familiesRef.current), []);

  return { selectedModels, setSelectedModels, allModelIds, modelLabel };
}
