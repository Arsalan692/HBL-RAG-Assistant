import { cn } from "@/lib/utils";

/**
 * Interaction-state classes, defined once and shared by the live components
 * and the states reference page at #/states.
 *
 * Passing no state gives the real interactive element, with :hover, :active and
 * :focus-visible doing the work. Passing a state forces that appearance, which
 * is how the reference page shows all three side by side without needing a
 * pointer. Because both paths read the same strings, the documentation cannot
 * drift away from the product.
 *
 * Motion contract — every transition below:
 *   duration  180ms (immediate feedback) … 260ms (things that travel)
 *   easing    cubic-bezier(0.32, 0.72, 0, 1)
 */

export type ForcedState = "hover" | "pressed" | "focused" | undefined;

/** Colour and shadow only — never width, height or border-width. */
const TINT = "transition-[background-color,color,border-color,box-shadow,transform,filter]";
const FAST = `${TINT} duration-180 ease-spring`;

const RING = "ring-3 ring-[var(--hbl-green-ring)]";

export function primaryButtonCls(state?: ForcedState) {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-lg bg-hbl-solid px-4 py-2.5",
    "text-sm font-medium text-hbl-on-solid outline-none",
    FAST,
    // Note on the motion spec: filled buttons deepen on hover in light mode
    // rather than lifting brightness. Lifting a fill that already sits at
    // 4.67:1 drops the label below AA, so the light theme darkens instead —
    // the dark theme still lifts, because there the fill is the bright step.
    !state &&
      "hover:bg-hbl-solid-hover active:scale-97 active:bg-hbl-solid-pressed focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
    state === "hover" && "bg-hbl-solid-hover",
    state === "pressed" && "scale-97 bg-hbl-solid-pressed",
    state === "focused" && RING,
  );
}

/**
 * Any interactive row: sidebar navigation, chat history, menu rows.
 * The tint fades in — the border stays put so nothing shifts on hover.
 */
export function rowCls(active: boolean, state?: ForcedState) {
  return cn(
    "group flex items-center gap-2.5 rounded-lg border-l-2 py-2 pl-2.5 pr-1.5 text-sm outline-none",
    FAST,
    active
      ? "border-l-hbl-green bg-accent font-medium text-accent-foreground"
      : "border-l-transparent text-hbl-primary",
    !active && !state && "hover:bg-black/4 active:bg-black/7 dark:hover:bg-white/5 dark:active:bg-white/8",
    !active && state === "hover" && "bg-black/4 dark:bg-white/5",
    !active && state === "pressed" && "bg-black/7 dark:bg-white/8",
    !state && "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
    state === "focused" && RING,
  );
}

export function sourceCardCls(active: boolean, state?: ForcedState) {
  return cn(
    "flex w-[248px] shrink-0 snap-start items-start gap-2.5 rounded-xl border bg-card p-3 text-left outline-none",
    "shadow-[var(--hbl-shadow)]",
    TINT,
    "duration-220 ease-spring",
    active ? "border-hbl-green bg-accent/45" : "border-border",
    !active && !state && "hover:-translate-y-px hover:border-hbl-green/45 hover:bg-accent/25 active:translate-y-0 active:scale-99",
    !active && state === "hover" && "-translate-y-px border-hbl-green/45 bg-accent/25",
    !active && state === "pressed" && "scale-99 border-hbl-green/45 bg-accent/40",
    !state && "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
    state === "focused" && RING,
  );
}

export function citationPillCls(active: boolean, state?: ForcedState) {
  return cn(
    // Sits slightly raised, like a footnote marker. No horizontal margin — the
    // space before it already exists in the answer text, and a margin after it
    // would detach the pill from the punctuation that follows.
    "inline-flex h-4 min-w-4 translate-y-[-2px] items-center justify-center align-middle outline-none",
    "rounded-full px-[3px] text-[10px] font-bold leading-none",
    FAST,
    active
      ? "bg-hbl-solid text-hbl-on-solid ring-1 ring-hbl-solid"
      : "bg-accent text-accent-foreground ring-1 ring-hbl-green/25",
    !active &&
      !state &&
      "hover:bg-hbl-solid hover:text-hbl-on-solid hover:ring-hbl-solid active:scale-97",
    !active && state === "hover" && "bg-hbl-solid text-hbl-on-solid ring-hbl-solid",
    !active &&
      state === "pressed" &&
      "scale-97 bg-hbl-solid-pressed text-hbl-on-solid ring-hbl-solid-pressed",
    state === "focused" && "ring-3 ring-[var(--hbl-green-ring)]",
  );
}

export function menuItemCls(state?: ForcedState, danger = false) {
  return cn(
    "flex cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 py-2 text-sm outline-none",
    FAST,
    danger ? "text-destructive" : "text-popover-foreground",
    !state && "data-[highlighted]:bg-black/5 dark:data-[highlighted]:bg-white/6 active:scale-99",
    state === "hover" && "bg-black/5 dark:bg-white/6",
    state === "pressed" && "scale-99 bg-black/8 dark:bg-white/10",
    state === "focused" && RING,
  );
}

/** Shared entrance classes for overlay surfaces. */
export const MENU_SURFACE = cn(
  "z-50 rounded-xl border border-border bg-popover p-1 text-popover-foreground",
  "shadow-[0_8px_24px_rgba(0,0,0,0.10)] dark:shadow-[0_8px_24px_rgba(0,0,0,0.5)]",
  "origin-[var(--radix-dropdown-menu-content-transform-origin)] animate-menu-in",
);
