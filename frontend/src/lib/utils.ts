import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Keyboard shortcut label for the current platform.
 * Macs get the glyph pressed straight against the key ("⌘K"); everyone else
 * gets the spelled-out modifier, which needs a separator ("Ctrl+K").
 */
export function shortcutLabel(key: string): string {
  const isMac = typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.userAgent);
  return isMac ? `⌘${key}` : `Ctrl+${key}`;
}
