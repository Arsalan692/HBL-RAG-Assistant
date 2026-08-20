import { cn } from "@/lib/utils";

/**
 * The official HBL assets, served from /public.
 *
 * Both are extracted from the supplied lockup rather than redrawn, so the
 * geometry and the brand colours (#009F8C teal, #E0DF00 lime) are exact.
 * They read correctly on both the light and dark canvas, so there is no
 * per-theme variant.
 *
 * `height` drives the size and width is derived from the artwork's own ratio.
 * Width is set explicitly rather than left as `auto`: these sit inside flex
 * columns, where the default `align-items: stretch` would otherwise pull an
 * auto-width image out to the full container width and distort it.
 */

const MARK_RATIO = 208 / 157;
const LOGO_RATIO = 794 / 157;

export function HblMark({ height = 22, className }: { height?: number; className?: string }) {
  return (
    <img
      src="/hbl-mark.png"
      alt=""
      aria-hidden="true"
      draggable={false}
      style={{ height, width: Math.round(height * MARK_RATIO) }}
      className={cn("shrink-0 select-none", className)}
    />
  );
}

export function HblLogo({ height = 20, className }: { height?: number; className?: string }) {
  return (
    <img
      src="/hbl-logo.png"
      alt="HBL"
      draggable={false}
      style={{ height, width: Math.round(height * LOGO_RATIO) }}
      className={cn("shrink-0 select-none", className)}
    />
  );
}

/**
 * The mark set on a tile, used where it stands in for an avatar beside an
 * assistant answer. The bare chevron alone does not read as a speaker.
 */
export function HblAvatar({ size = 26, className }: { size?: number; className?: string }) {
  return (
    <div
      style={{ width: size, height: size }}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-lg border border-border bg-card",
        className,
      )}
    >
      <HblMark height={Math.round(size * 0.46)} />
    </div>
  );
}
