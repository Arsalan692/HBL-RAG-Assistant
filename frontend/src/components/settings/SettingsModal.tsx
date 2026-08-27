import { useEffect, useRef, useState } from "react";
import { Database, Keyboard, Monitor, Moon, Palette, ShieldCheck, Sun, X } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import {
  FONT_SIZE_DEFAULT,
  FONT_SIZE_MAX,
  FONT_SIZE_MIN,
  useSettings,
  type ThemeMode,
} from "@/components/settings/SettingsProvider";
import { listDocuments } from "@/lib/api";
import { cn, shortcutLabel } from "@/lib/utils";

type SectionId = "appearance" | "knowledge" | "privacy" | "shortcuts";

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: "appearance", label: "Appearance", icon: <Palette size={15} /> },
  { id: "knowledge", label: "Knowledge bases", icon: <Database size={15} /> },
  { id: "privacy", label: "Data & privacy", icon: <ShieldCheck size={15} /> },
  { id: "shortcuts", label: "Shortcuts", icon: <Keyboard size={15} /> },
];

const THEME_OPTIONS: { value: ThemeMode; label: string; icon: React.ReactNode }[] = [
  { value: "light", label: "Light", icon: <Sun size={13} /> },
  { value: "dark", label: "Dark", icon: <Moon size={13} /> },
  { value: "system", label: "System", icon: <Monitor size={13} /> },
];

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-border py-4 last:border-b-0">
      <div className="min-w-0">
        <p className="text-sm font-medium leading-5 text-hbl-primary">{label}</p>
        {hint && <p className="mt-0.5 text-xs leading-5 text-hbl-secondary">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={cn(
        "relative h-6.5 w-11 shrink-0 rounded-full outline-none",
        "transition-colors duration-180 ease-spring",
        "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
        on ? "bg-hbl-green" : "bg-switch-background",
      )}
    >
      <span
        className={cn(
          "absolute top-[3px] h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.25)]",
          "transition-[left] duration-180 ease-spring",
          on ? "left-[21px]" : "left-[3px]",
        )}
      />
    </button>
  );
}

function AppearancePane() {
  const { themeMode, setThemeMode, fontSize, setFontSize, reduceMotion, setReduceMotion } =
    useSettings();

  return (
    <div>
      <Field label="Theme" hint="System follows your device setting.">
        <div className="inline-flex gap-0.5 rounded-lg bg-muted p-0.5">
          {THEME_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setThemeMode(opt.value)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs outline-none",
                "transition-all duration-180 ease-spring active:scale-97",
                "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                themeMode === opt.value
                  ? "bg-card font-medium text-hbl-primary shadow-[0_1px_3px_rgba(0,0,0,0.08)] dark:shadow-none"
                  : "text-hbl-secondary hover:text-hbl-primary",
              )}
            >
              {opt.icon}
              {opt.label}
            </button>
          ))}
        </div>
      </Field>

      <Field label="Text size" hint={`${fontSize}px base — affects the whole interface.`}>
        <div className="flex w-52 items-center gap-2.5">
          <span className="text-[11px] text-hbl-tertiary">A</span>
          <input
            type="range"
            min={FONT_SIZE_MIN}
            max={FONT_SIZE_MAX}
            step={1}
            value={fontSize}
            aria-label="Text size"
            onChange={(e) => setFontSize(Number(e.target.value))}
            className="hbl-range flex-1 focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]"
          />
          <span className="text-[15px] leading-none text-hbl-tertiary">A</span>
        </div>
      </Field>

      <Field
        label="Reduce motion"
        hint="Keeps transitions instant. Panels and menus still appear, they just don't travel."
      >
        <Toggle on={reduceMotion} onChange={setReduceMotion} label="Reduce motion" />
      </Field>

      {fontSize !== FONT_SIZE_DEFAULT && (
        <button
          type="button"
          onClick={() => setFontSize(FONT_SIZE_DEFAULT)}
          className="mt-4 text-xs font-medium text-hbl-green outline-none hover:underline focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]"
        >
          Reset text size to {FONT_SIZE_DEFAULT}px
        </button>
      )}
    </div>
  );
}

/**
 * There is one corpus, so there is nothing to choose between.
 *
 * This pane used to list three knowledge bases with document counts — "Retail
 * Banking SOPs · 34 documents", and two more — none of which existed. The same
 * fiction appeared as a chip in the header and the composer, implying a
 * selector the product has never had.
 */
function KnowledgePane({ onOpenDocuments }: { onOpenDocuments: () => void }) {
  const [count, setCount] = useState<number | null>(null);

  useEffect(() => {
    listDocuments()
      .then((docs) => setCount(docs.length))
      .catch(() => setCount(null));
  }, []);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent">
          <Database size={15} className="text-accent-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium leading-5 text-hbl-primary">
            {count === null ? "Documents" : `${count} document${count === 1 ? "" : "s"}`}
          </p>
          <p className="truncate text-xs leading-4 text-hbl-tertiary">
            Every answer comes from these and nothing else
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onOpenDocuments}
        className={cn(
          "self-start rounded-lg border border-border px-3 py-1.5 text-[13px] text-hbl-secondary outline-none",
          "transition-all duration-180 ease-spring hover:bg-accent",
          "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
        )}
      >
        Manage documents
      </button>
    </div>
  );
}

/**
 * What actually happens to the data, which is not what this pane used to say.
 *
 * It previously offered a "Store chat history" toggle described as
 * "Conversations are kept on the bank's own servers", a 90-day retention
 * period, and a "Clear all conversations" button. None of it was real. A false
 * assurance about where confidential questions are stored is the worst thing
 * on this screen to leave as mock text, and the truth is a better answer
 * anyway: nothing is stored and nothing leaves the machine.
 */
function PrivacyPane() {
  return (
    <div>
      <Field
        label="Where the models run"
        hint="Every model — reading, search and the answer itself — runs on this machine. No question or document is ever sent to an outside service."
      >
        <span className="text-sm font-medium text-hbl-green">On this machine</span>
      </Field>
      <Field
        label="Chat history"
        hint="Conversations live in this browser tab only. Closing or reloading the app discards them; nothing is written to disk."
      >
        <span className="text-sm text-hbl-secondary">Not stored</span>
      </Field>
      <Field
        label="Documents"
        hint="The PDFs, the text read from them and the search index all stay in this installation. Removing a document deletes all three."
      >
        <span className="text-sm text-hbl-secondary">Kept locally</span>
      </Field>
    </div>
  );
}

function ShortcutsPane() {
  const rows = [
    ["Search conversations", shortcutLabel("K")],
    ["New chat", shortcutLabel("Shift+O")],
    ["Toggle sidebar", shortcutLabel("B")],
    ["Send message", "Enter"],
    ["New line", "Shift+Enter"],
    ["Close panel or dialog", "Esc"],
  ];
  return (
    <dl className="flex flex-col">
      {rows.map(([label, keys]) => (
        <div
          key={label}
          className="flex items-center justify-between gap-4 border-b border-border py-3 last:border-b-0"
        >
          <dt className="text-sm text-hbl-primary">{label}</dt>
          <dd>
            <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 font-sans text-[11px] font-medium text-hbl-secondary">
              {keys}
            </kbd>
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SettingsModal({
  onClose,
  onOpenDocuments,
}: {
  onClose: () => void;
  onOpenDocuments: () => void;
}) {
  const [section, setSection] = useState<SectionId>("appearance");
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const panes: Record<SectionId, React.ReactNode> = {
    appearance: <AppearancePane />,
    knowledge: <KnowledgePane onOpenDocuments={onOpenDocuments} />,
    privacy: <PrivacyPane />,
    shortcuts: <ShortcutsPane />,
  };

  return (
    <div
      className="fixed inset-0 z-50 flex animate-overlay-in items-center justify-center bg-black/45 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => {
        if (!panelRef.current?.contains(e.target as Node)) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        className={cn(
          "flex max-h-[80vh] w-full max-w-[560px] animate-modal-in overflow-hidden rounded-2xl",
          "border border-border bg-popover shadow-[0_24px_64px_rgba(0,0,0,0.22)]",
        )}
      >
        {/* Left nav */}
        <nav className="flex w-[184px] shrink-0 flex-col gap-0.5 border-r border-border p-2.5">
          <p className="px-2.5 pb-2 pt-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
            Settings
          </p>
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSection(s.id)}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] outline-none",
                "transition-all duration-180 ease-spring",
                "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
                section === s.id
                  ? "bg-accent font-medium text-accent-foreground"
                  : "text-hbl-primary hover:bg-black/4 dark:hover:bg-white/5",
              )}
            >
              <span className={section === s.id ? "text-hbl-green" : "text-hbl-tertiary"}>
                {s.icon}
              </span>
              <span className="truncate">{s.label}</span>
            </button>
          ))}
        </nav>

        {/* Pane */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-13 shrink-0 items-center justify-between border-b border-border pl-5 pr-3">
            <h2 className="text-sm font-semibold text-hbl-primary">
              {SECTIONS.find((s) => s.id === section)?.label}
            </h2>
            <IconButton label="Close settings" size="sm" onClick={onClose}>
              <X size={16} />
            </IconButton>
          </div>
          <div className="hbl-scroll min-h-0 flex-1 overflow-y-auto px-5 py-2">
            {panes[section]}
          </div>
        </div>
      </div>
    </div>
  );
}
