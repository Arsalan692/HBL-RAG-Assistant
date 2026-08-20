import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

export function CodeBlock({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard is unavailable over plain http on some hosts; fail quietly.
    }
  }

  return (
    <div className="group relative mb-4 overflow-hidden rounded-xl border border-border bg-muted">
      <div className="flex items-center justify-between border-b border-border px-3.5 py-1.5">
        <span className="text-[10px] uppercase tracking-[0.06em] text-hbl-tertiary">
          {language || "text"}
        </span>
        <button
          type="button"
          onClick={copy}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium",
            "text-hbl-tertiary transition-all duration-180 ease-spring active:scale-97",
            "hover:bg-black/5 hover:text-hbl-primary dark:hover:bg-white/7",
          )}
        >
          {copied ? (
            <>
              <Check size={12} className="text-hbl-green" /> Copied
            </>
          ) : (
            <>
              <Copy size={12} /> Copy
            </>
          )}
        </button>
      </div>
      <pre className="hbl-scroll overflow-x-auto px-3.5 py-3">
        <code className="font-mono text-[12.5px] leading-6 text-hbl-primary">{code}</code>
      </pre>
    </div>
  );
}
