import { useState } from "react";
import { Check, Copy, RefreshCw, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import { cn } from "@/lib/utils";

type Vote = "up" | "down" | null;

export function AnswerActions({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);
  const [vote, setVote] = useState<Vote>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard is unavailable over plain http on some hosts; fail quietly.
    }
  }

  return (
    <div className="mt-3 flex items-center gap-0.5">
      <IconButton label={copied ? "Copied" : "Copy answer"} size="sm" onClick={copy}>
        {copied ? <Check size={14} className="text-hbl-green" /> : <Copy size={14} />}
      </IconButton>

      <IconButton label="Regenerate" size="sm">
        <RefreshCw size={14} />
      </IconButton>

      <IconButton
        label="Good answer"
        size="sm"
        onClick={() => setVote((v) => (v === "up" ? null : "up"))}
        className={cn(vote === "up" && "text-hbl-green")}
      >
        <ThumbsUp size={14} />
      </IconButton>

      <IconButton
        label="Needs work"
        size="sm"
        onClick={() => setVote((v) => (v === "down" ? null : "down"))}
        className={cn(vote === "down" && "text-destructive")}
      >
        <ThumbsDown size={14} />
      </IconButton>

      <IconButton label="View reasoning" size="sm">
        <Sparkles size={14} />
      </IconButton>
    </div>
  );
}
