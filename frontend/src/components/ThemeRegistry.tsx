"use client";
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v14-appRouter";
import { lightTheme, darkTheme } from "../theme";

const STORAGE_KEY = "crucible_is_dark";

interface ThemeModeValue {
  isDark: boolean;
  toggleMode: () => void;
}

const ThemeModeContext = createContext<ThemeModeValue>({
  isDark: true,
  toggleMode: () => {},
});

/**
 * Read the current mode and flip it.
 *
 * This is the single owner of theme state. `page.tsx` used to keep its own
 * `isDark` and sync the two through localStorage plus a custom DOM event,
 * which meant two sources of truth for one value.
 */
export function useThemeMode() {
  return useContext(ThemeModeContext);
}

export default function ThemeRegistry({
  children,
}: {
  children: React.ReactNode;
}) {
  const [isDark, setIsDark] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch {}
    if (saved !== null) {
      setIsDark(JSON.parse(saved));
      return;
    }
    // No choice made here yet: follow the system's light/dark setting, and
    // keep following it until the person picks one with the toggle.
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!query) return;
    setIsDark(query.matches);
    const follow = (e: MediaQueryListEvent) => {
      try {
        if (localStorage.getItem(STORAGE_KEY) !== null) return;
      } catch {}
      setIsDark(e.matches);
    };
    query.addEventListener?.("change", follow);
    return () => query.removeEventListener?.("change", follow);
  }, []);

  const toggleMode = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);

  // Mirror onto the document so plain CSS can react to the mode too.
  useEffect(() => {
    document.documentElement.setAttribute(
      "data-theme",
      isDark ? "dark" : "light",
    );
  }, [isDark]);

  const value = useMemo<ThemeModeValue>(
    () => ({ isDark, toggleMode }),
    [isDark, toggleMode],
  );

  return (
    <AppRouterCacheProvider options={{ key: "mui" }}>
      <ThemeModeContext.Provider value={value}>
        <ThemeProvider
          theme={mounted ? (isDark ? darkTheme : lightTheme) : darkTheme}
        >
          <CssBaseline />
          {children}
        </ThemeProvider>
      </ThemeModeContext.Provider>
    </AppRouterCacheProvider>
  );
}
