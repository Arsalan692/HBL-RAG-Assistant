import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { FileText, Pin, Plus } from "lucide-react";
import { CitationPill } from "@/components/chat/CitationPill";
import { SourceCard } from "@/components/chat/SourcesRow";
import { useSettings } from "@/components/settings/SettingsProvider";
import { IconButton } from "@/components/common/IconButton";
import { Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { menuItemCls, primaryButtonCls, rowCls, type ForcedState } from "@/lib/variants";
import { STREAMED_ANSWER } from "@/data/mock";

const STATES: { key: ForcedState; label: string }[] = [
  { key: undefined, label: "Default" },
  { key: "hover", label: "Hover" },
  { key: "pressed", label: "Pressed" },
  { key: "focused", label: "Focused" },
];

const MOTION = [
  ["Interactive row — hover", "Background tint fades in. The border never flips.", "180ms"],
  ["Button — press", "Scales to 0.97 and steps to the pressed fill.", "180ms"],
  [
    "Button — hover",
    "Steps one shade toward contrast: darker in light mode, lighter in dark. Not a brightness filter — that would push the label below AA in light mode.",
    "180ms",
  ],
  ["Dropdown / menu open", "Scale 0.96 → 1 from the trigger origin, plus 8px translateY. Shadow fades in.", "180ms"],
  ["Sidebar collapse", "Width animates 280px → 68px. Labels cross-fade out; icons stay anchored.", "260ms"],
  ["New message", "Fades in with an 8px rise.", "260ms"],
  ["Theme switch", "Full-canvas cross-fade via the View Transitions API. No flash.", "260ms"],
  ["Source panel", "Springs in from the right, 28px travel. Closes on Esc.", "260ms"],
  ["Modal open", "Scale 0.96 → 1 with an 8px rise; scrim fades in behind.", "220ms"],
  ["Skeleton shimmer", "Slow sweep, looping.", "1600ms"],
];

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border py-8">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
        {title}
      </h2>
      {note && <p className="mt-1.5 max-w-2xl text-[13px] leading-5 text-hbl-secondary">{note}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function StateGrid({
  render,
  width = 260,
}: {
  render: (state: ForcedState) => React.ReactNode;
  width?: number;
}) {
  return (
    <div className="flex flex-wrap gap-6">
      {STATES.map(({ key, label }) => (
        <div key={label} className="flex flex-col gap-2.5" style={{ width }}>
          <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
            {label}
          </span>
          <div className="flex min-h-11 items-center">{render(key)}</div>
        </div>
      ))}
    </div>
  );
}

export default function StatesPage() {
  const { theme, toggleTheme } = useSettings();
  const source = STREAMED_ANSWER.sources[0];

  return (
    <TooltipPrimitive.Provider delayDuration={350}>
      <div className="hbl-scroll h-screen overflow-y-auto bg-background">
        {/* Wide enough that all four states sit on one row for every specimen. */}
        <div className="mx-auto max-w-7xl px-8 pb-24 pt-12">
        <header className="flex items-start justify-between gap-6 pb-8">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.07em] text-hbl-tertiary">
              HBL RAG Assistant · Handoff
            </p>
            <h1 className="mt-2 text-[28px] font-semibold leading-9 tracking-[-0.01em] text-hbl-primary">
              Interaction states &amp; motion
            </h1>
            <p className="mt-2 max-w-2xl text-[15px] leading-6 text-hbl-secondary">
              Every specimen below is the production component, forced into each state. The classes
              come from a single shared file, so this page cannot drift away from the product.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton label="Toggle theme" onClick={toggleTheme}>
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </IconButton>
            <a
              href="#/"
              className="rounded-lg px-3 py-2 text-[13px] font-medium text-hbl-green outline-none hover:underline"
            >
              Back to app
            </a>
          </div>
        </header>

        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-[13px] leading-6 text-hbl-secondary">
            <span className="font-medium text-hbl-primary">Motion contract.</span> One easing curve
            throughout —{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-hbl-primary">
              cubic-bezier(0.32, 0.72, 0, 1)
            </code>
            . Durations sit between 180ms and 260ms: 180 for immediate feedback, 260 for anything
            that travels a distance. Nothing animates width or border thickness on hover.
          </p>
        </div>

        <Section
          title="Primary button"
          note="Filled controls use the accessible fill (#008373 light, #2DD4BF dark), not the brand teal #009F8C — white on the brand colour is only 3.31:1. The brand teal is still used everywhere nothing sits on top of it: borders, focus rings, progress bars, the streaming caret and the mark."
        >
          <StateGrid
            width={180}
            render={(state) => (
              <button type="button" className={primaryButtonCls(state)}>
                <Plus size={16} />
                New chat
              </button>
            )}
          />
        </Section>

        <Section
          title="Sidebar item"
          note="The tint fades in behind the label. The 2px leading rule stays transparent until the row is actually selected, so hovering never shifts the text."
        >
          <StateGrid
            render={(state) => (
              <div className={cn(rowCls(false, state), "w-full cursor-pointer")}>
                <Pin size={13} className="shrink-0 text-hbl-tertiary" />
                <span className="min-w-0 flex-1 truncate leading-5">
                  Sanctions screening escalation
                </span>
              </div>
            )}
          />
          <div className="mt-6 flex flex-col gap-2.5" style={{ width: 260 }}>
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
              Selected
            </span>
            <div className={cn(rowCls(true), "w-full cursor-pointer")}>
              <Pin size={13} className="shrink-0 text-hbl-green" />
              <span className="min-w-0 flex-1 truncate leading-5">
                Sanctions screening escalation
              </span>
            </div>
          </div>
        </Section>

        <Section
          title="Source card"
          note="Rises one pixel on hover and settles back on press. Slightly slower than the buttons at 220ms, because the card carries more visual weight."
        >
          <StateGrid width={264} render={(state) => <SourceCard source={source} state={state} />} />
        </Section>

        <Section
          title="Citation pill"
          note="Inline in the answer text, so it must not disturb the line box. Hover fills it solid; the active pill stays filled while its source panel is open."
        >
          <StateGrid
            width={140}
            render={(state) => (
              <p className="text-[15px] leading-7 text-hbl-primary">
                …review cycle <CitationPill index={3} state={state} />.
              </p>
            )}
          />
          <div className="mt-6 flex flex-col gap-2.5" style={{ width: 140 }}>
            <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
              Active
            </span>
            <p className="text-[15px] leading-7 text-hbl-primary">
              …review cycle <CitationPill index={3} active />.
            </p>
          </div>
        </Section>

        <Section
          title="Dropdown menu item"
          note="Radix drives the real highlight through data-highlighted, so keyboard navigation and pointer hover produce the same appearance."
        >
          <StateGrid
            render={(state) => (
              <div className={cn(menuItemCls(state), "w-full")}>
                <FileText size={14} className="text-hbl-tertiary" />
                Source documents
              </div>
            )}
          />
        </Section>

        <Section title="Timing reference" note="What each transition does, and how long it takes.">
          <div className="hbl-scroll overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm">
              <thead>
                <tr>
                  <th className="whitespace-nowrap border-b border-border pb-2 pr-6 text-[12px] font-medium text-hbl-secondary">
                    Element
                  </th>
                  <th className="border-b border-border pb-2 pr-6 text-[12px] font-medium text-hbl-secondary">
                    Behaviour
                  </th>
                  <th className="whitespace-nowrap border-b border-border pb-2 text-[12px] font-medium text-hbl-secondary">
                    Duration
                  </th>
                </tr>
              </thead>
              <tbody>
                {MOTION.map(([element, behaviour, duration]) => (
                  <tr key={element}>
                    <td className="whitespace-nowrap border-b border-border/60 py-2.5 pr-6 align-top text-[14px] font-medium leading-6 text-hbl-primary">
                      {element}
                    </td>
                    <td className="border-b border-border/60 py-2.5 pr-6 align-top text-[14px] leading-6 text-hbl-secondary">
                      {behaviour}
                    </td>
                    <td className="whitespace-nowrap border-b border-border/60 py-2.5 align-top text-[14px] leading-6 tabular-nums text-hbl-primary">
                      {duration}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>

        <Section
          title="Reduced motion"
          note="Settings → Appearance → Reduce motion, and the operating system preference, both collapse every duration above to effectively zero. End states are preserved — nothing disappears, it just stops travelling."
        >
          <p className="text-[13px] leading-6 text-hbl-secondary">
            Implemented once, as a class on the document root plus a{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px] text-hbl-primary">
              prefers-reduced-motion
            </code>{" "}
            media query. Individual components carry no reduced-motion branches.
          </p>
          </Section>
        </div>
      </div>
    </TooltipPrimitive.Provider>
  );
}
