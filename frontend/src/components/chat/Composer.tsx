import { useEffect, useRef, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ArrowUp, Database, Mic, Paperclip, Square, Upload } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import { cn } from "@/lib/utils";
import { MENU_SURFACE, menuItemCls } from "@/lib/variants";

const MAX_HEIGHT = 200;

/** On mobile the mic and knowledge-base controls fold into the attach menu. */
function AttachMenu({ compact }: { compact: boolean }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <IconButton label="Attach" size="sm" tooltip={false}>
          <Paperclip size={15} />
        </IconButton>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="start" side="top" sideOffset={8} className={cn(MENU_SURFACE, "w-56")}>
          <DropdownMenu.Item className={menuItemCls()}>
            <Upload size={14} className="text-hbl-tertiary" /> Upload a document
          </DropdownMenu.Item>
          {compact && (
            <>
              <DropdownMenu.Item className={menuItemCls()}>
                <Mic size={14} className="text-hbl-tertiary" /> Dictate
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-border" />
              <DropdownMenu.Item className={menuItemCls()}>
                <Database size={14} className="text-hbl-green" /> Retail Banking SOPs
              </DropdownMenu.Item>
            </>
          )}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function Composer({
  value,
  onChange,
  onSubmit,
  streaming = false,
  onStop,
  isMobile = false,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (v: string) => void;
  streaming?: boolean;
  onStop?: () => void;
  isMobile?: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [focused, setFocused] = useState(false);

  // Grow with content, then scroll internally once it gets tall.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? "auto" : "hidden";
  }, [value]);

  const canSend = value.trim().length > 0 && !streaming;

  function submit() {
    if (!canSend) return;
    onSubmit(value.trim());
  }

  return (
    <div className="pointer-events-none sticky bottom-0 z-20">
      {/* Fade so the thread dissolves behind the composer rather than colliding with it. */}
      <div className="pointer-events-none h-8 bg-gradient-to-b from-transparent to-background" />

      <div
        className={cn(
          "pointer-events-auto bg-background/85 backdrop-blur-xl",
          isMobile ? "px-4 pb-[max(1rem,env(safe-area-inset-bottom))]" : "px-6 pb-4",
        )}
      >
        <div className="mx-auto w-full max-w-[760px]">
          <div
            className={cn(
              "overflow-hidden rounded-2xl border bg-card",
              "shadow-[var(--hbl-shadow)] transition-all duration-180 ease-spring",
              focused ? "border-hbl-green ring-3 ring-[var(--hbl-green-ring)]" : "border-border",
            )}
          >
            <textarea
              ref={textareaRef}
              value={value}
              rows={1}
              placeholder="Ask about any HBL policy or SOP…"
              onChange={(e) => onChange(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              className="hbl-scroll block w-full resize-none bg-transparent px-4 pb-2 pt-3.5 text-[15px] leading-6 text-hbl-primary outline-none placeholder:text-hbl-tertiary"
            />

            <div className="flex items-center justify-between gap-2 px-2.5 pb-2.5 pt-1">
              <div className="flex min-w-0 items-center gap-1">
                <AttachMenu compact={isMobile} />

                {!isMobile && (
                  <>
                    <IconButton label="Dictate" size="sm">
                      <Mic size={15} />
                    </IconButton>
                    <button
                      type="button"
                      className={cn(
                        "ml-1 inline-flex min-w-0 items-center gap-1.5 rounded-full border border-border",
                        "bg-muted px-2.5 py-1 text-xs font-medium text-hbl-secondary outline-none",
                        "transition-all duration-180 ease-spring active:scale-97",
                        "hover:border-hbl-green/40 hover:bg-accent hover:text-accent-foreground",
                        "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                      )}
                    >
                      <Database size={11} className="shrink-0" />
                      <span className="truncate">Retail Banking SOPs</span>
                    </button>
                  </>
                )}
              </div>

              {streaming ? (
                <button
                  type="button"
                  onClick={onStop}
                  aria-label="Stop generating"
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-hbl-primary text-hbl-canvas",
                    "outline-none transition-all duration-180 ease-spring hover:brightness-110 active:scale-97",
                    "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                  )}
                >
                  <Square size={11} fill="currentColor" strokeWidth={0} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submit}
                  disabled={!canSend}
                  aria-label="Send message"
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full outline-none",
                    "transition-all duration-180 ease-spring",
                    "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                    canSend
                      ? "bg-hbl-solid text-hbl-on-solid hover:bg-hbl-solid-hover active:scale-97 active:bg-hbl-solid-pressed"
                      : "cursor-not-allowed bg-muted text-hbl-tertiary",
                  )}
                >
                  <ArrowUp size={16} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>

          <p className="pt-2.5 text-center text-xs leading-4 text-hbl-tertiary">
            HBL RAG Assistant can make mistakes. Verify against the source document.
          </p>
        </div>
      </div>
    </div>
  );
}
