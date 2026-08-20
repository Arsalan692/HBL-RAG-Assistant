import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type ThemeMode = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";

interface Settings {
  themeMode: ThemeMode;
  /** What themeMode actually resolves to right now. */
  theme: ResolvedTheme;
  fontSize: number;
  reduceMotion: boolean;
  setThemeMode: (mode: ThemeMode) => void;
  setFontSize: (px: number) => void;
  setReduceMotion: (on: boolean) => void;
  /** Convenience for the top-bar toggle: flips between light and dark. */
  toggleTheme: () => void;
}

const SettingsContext = createContext<Settings | null>(null);

const KEYS = {
  theme: "hbl-theme-mode",
  fontSize: "hbl-font-size",
  reduceMotion: "hbl-reduce-motion",
};

export const FONT_SIZE_MIN = 13;
export const FONT_SIZE_MAX = 18;
export const FONT_SIZE_DEFAULT = 15;

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function readThemeMode(): ThemeMode {
  const stored = localStorage.getItem(KEYS.theme);
  return stored === "light" || stored === "dark" || stored === "system" ? stored : "system";
}

/**
 * Repaints the page inside a view transition where the browser supports one,
 * which gives the theme switch a full-canvas cross-fade instead of a flash.
 */
function applyWithCrossFade(apply: () => void, enabled: boolean) {
  const doc = document as Document & {
    startViewTransition?: (cb: () => void) => { finished: Promise<void> };
  };
  if (!enabled || typeof doc.startViewTransition !== "function") {
    apply();
    return;
  }
  doc.startViewTransition(apply);
}

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [themeMode, setThemeModeState] = useState<ThemeMode>(readThemeMode);
  const [systemPref, setSystemPref] = useState<ResolvedTheme>(systemTheme);
  const [fontSize, setFontSizeState] = useState<number>(() => {
    const stored = Number(localStorage.getItem(KEYS.fontSize));
    return Number.isFinite(stored) && stored >= FONT_SIZE_MIN && stored <= FONT_SIZE_MAX
      ? stored
      : FONT_SIZE_DEFAULT;
  });
  const [reduceMotion, setReduceMotionState] = useState<boolean>(
    () => localStorage.getItem(KEYS.reduceMotion) === "true",
  );

  // Track the OS preference so "System" stays live rather than snapshotting.
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setSystemPref(mq.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme: ResolvedTheme = themeMode === "system" ? systemPref : themeMode;

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
  }, [theme]);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-size", `${fontSize}px`);
    localStorage.setItem(KEYS.fontSize, String(fontSize));
  }, [fontSize]);

  useEffect(() => {
    document.documentElement.classList.toggle("reduce-motion", reduceMotion);
    localStorage.setItem(KEYS.reduceMotion, String(reduceMotion));
  }, [reduceMotion]);

  const setThemeMode = useCallback(
    (mode: ThemeMode) => {
      applyWithCrossFade(() => {
        setThemeModeState(mode);
        localStorage.setItem(KEYS.theme, mode);
      }, !reduceMotion);
    },
    [reduceMotion],
  );

  const toggleTheme = useCallback(() => {
    setThemeMode(theme === "dark" ? "light" : "dark");
  }, [theme, setThemeMode]);

  const value = useMemo<Settings>(
    () => ({
      themeMode,
      theme,
      fontSize,
      reduceMotion,
      setThemeMode,
      setFontSize: setFontSizeState,
      setReduceMotion: setReduceMotionState,
      toggleTheme,
    }),
    [themeMode, theme, fontSize, reduceMotion, setThemeMode, toggleTheme],
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

export function useSettings() {
  const ctx = useContext(SettingsContext);
  if (!ctx) throw new Error("useSettings must be used inside SettingsProvider");
  return ctx;
}
