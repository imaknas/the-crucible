"use client";
import React, { useState, useEffect } from "react";
import { ThemeProvider } from "@mui/material/styles";
import CssBaseline from "@mui/material/CssBaseline";
import { AppRouterCacheProvider } from "@mui/material-nextjs/v14-appRouter";
import { lightTheme, darkTheme } from "../theme";

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
    const savedDark = localStorage.getItem("crucible_is_dark");
    if (savedDark !== null) {
      setIsDark(JSON.parse(savedDark));
    }
  }, []);

  // Use a listener to sync theme if page.tsx toggles it
  useEffect(() => {
    const handleStorageChange = () => {
      const savedDark = localStorage.getItem("crucible_is_dark");
      if (savedDark !== null) {
        setIsDark(JSON.parse(savedDark));
      }
    };
    window.addEventListener("storage", handleStorageChange);
    // Also dispatch a custom event from page.tsx so same-window updates work instantly
    window.addEventListener(
      "themeChange",
      handleStorageChange as EventListener,
    );

    return () => {
      window.removeEventListener("storage", handleStorageChange);
      window.removeEventListener(
        "themeChange",
        handleStorageChange as EventListener,
      );
    };
  }, []);

  return (
    <AppRouterCacheProvider options={{ key: "mui" }}>
      <ThemeProvider
        theme={mounted ? (isDark ? darkTheme : lightTheme) : darkTheme}
      >
        <CssBaseline />
        {children}
      </ThemeProvider>
    </AppRouterCacheProvider>
  );
}
