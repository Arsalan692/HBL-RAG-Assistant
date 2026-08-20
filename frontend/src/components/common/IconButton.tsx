import { forwardRef } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name, also shown as the tooltip. */
  label: string;
  size?: "sm" | "md";
  active?: boolean;
  /** Set false for buttons inside a row where tooltips would be noisy. */
  tooltip?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, size = "md", active = false, tooltip = true, className, children, ...props },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      className={cn(
        "inline-flex items-center justify-center rounded-lg transition-colors",
        "text-hbl-tertiary hover:bg-black/5 hover:text-hbl-primary dark:hover:bg-white/7",
        "disabled:pointer-events-none disabled:opacity-45",
        active && "text-hbl-green",
        size === "sm" ? "h-7 w-7" : "h-9 w-9",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );

  if (!tooltip) return button;

  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{button}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className={cn(
            "z-50 rounded-lg px-2.5 py-1.5 text-xs leading-4 text-[#F2F4F3] shadow-lg",
            "bg-[#1A1E1C] dark:bg-[#2D3330]",
            "animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
          )}
        >
          {label}
          <TooltipPrimitive.Arrow className="fill-[#1A1E1C] dark:fill-[#2D3330]" width={10} height={5} />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
});
