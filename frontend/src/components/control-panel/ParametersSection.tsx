import React from "react";
import { Box, Stack } from "@mui/material";
import { BookOpen, Globe } from "lucide-react";
import type { Toggles } from "@/lib/types";
import { SectionHeader, ToggleRow } from "./primitives";

/** Per-message switches sent with every request (RAG, web search). */
export default function ParametersSection({
  isDark,
  toggles,
  setToggles,
}: {
  isDark: boolean;
  toggles: Toggles;
  setToggles: React.Dispatch<React.SetStateAction<Toggles>>;
}) {
  return (
    <Box>
      <SectionHeader label="Parameters" />
      <Stack spacing={1}>
        <ToggleRow
          isDark={isDark}
          label="Search my documents"
          subtitle="Looks through the documents you've uploaded and pulls in anything relevant before answering."
          icon={<BookOpen width={16} height={16} />}
          checked={toggles.use_rag}
          onChange={() =>
            setToggles((prev) => ({
              ...prev,
              use_rag: !prev.use_rag,
            }))
          }
        />
        <ToggleRow
          isDark={isDark}
          label="Web Search Grounding"
          subtitle="Allows the model to access the live internet to ground its answers using its native search tool."
          icon={<Globe width={16} height={16} />}
          checked={toggles.use_web_search}
          onChange={() =>
            setToggles((prev) => ({
              ...prev,
              use_web_search: !prev.use_web_search,
            }))
          }
        />
      </Stack>
    </Box>
  );
}
