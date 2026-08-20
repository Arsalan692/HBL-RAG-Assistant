import { useCallback, useEffect, useRef, useState } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { Composer } from "@/components/chat/Composer";
import { EmptyState } from "@/components/chat/EmptyState";
import { Thread, type StreamingState } from "@/components/chat/Thread";
import type { RetrievalStep } from "@/components/chat/RetrievalStepper";
import { SettingsModal } from "@/components/settings/SettingsModal";
import { SourcePanel } from "@/components/sources/SourcePanel";
import { STREAMED_ANSWER, THREAD } from "@/data/mock";
import { useIsMobile } from "@/lib/useMediaQuery";
import type { ActiveCitation, AssistantMessage, Message, Source } from "@/types";

/** Pacing of the simulated answer. Replaced by real SSE events in Phase 06. */
const STEP_DELAYS: { at: number; step: RetrievalStep }[] = [
  { at: 900, step: "reading" },
  { at: 1900, step: "composing" },
];
const TYPE_INTERVAL_MS = 26;
const WORDS_PER_TICK = 2;

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<ActiveCitation | null>(null);
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const isMobile = useIsMobile();
  const timers = useRef<number[]>([]);
  const interval = useRef<number | null>(null);

  const clearTimers = useCallback(() => {
    timers.current.forEach(window.clearTimeout);
    timers.current = [];
    if (interval.current !== null) {
      window.clearInterval(interval.current);
      interval.current = null;
    }
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const openSource =
    activeCitation === null
      ? null
      : (messages
          .filter((m): m is AssistantMessage => m.role === "assistant")
          .find((m) => m.id === activeCitation.messageId)
          ?.sources.find((s) => s.id === activeCitation.sourceId) ?? null);

  /** Commits a finished (or stopped) answer into the thread. */
  const commit = useCallback((question: string, content: string) => {
    const stamp = Date.now();
    setMessages((prev) => [
      ...prev,
      { id: `u-${stamp}`, role: "user", content: question },
      {
        id: `a-${stamp}`,
        role: "assistant",
        content,
        sources: STREAMED_ANSWER.sources,
      },
    ]);
    setStreaming(null);
  }, []);

  /**
   * Simulates retrieval and generation: the stepper advances, then the answer
   * is revealed a couple of words at a time. Swapped for the real SSE stream
   * once the backend exists — the component tree does not change.
   */
  const send = useCallback(
    (question: string) => {
      clearTimers();
      setDraft("");
      setActiveCitation(null);
      setActiveChatId((id) => id ?? "c1");
      setStreaming({
        question,
        step: "searching",
        partial: "",
        documentCount: 1248,
        sourceCount: STREAMED_ANSWER.sources.length,
        sources: STREAMED_ANSWER.sources,
      });

      STEP_DELAYS.forEach(({ at, step }) => {
        timers.current.push(
          window.setTimeout(() => setStreaming((s) => (s ? { ...s, step } : s)), at),
        );
      });

      timers.current.push(
        window.setTimeout(() => {
          const words = STREAMED_ANSWER.content.split(/(\s+)/);
          let cursor = 0;

          interval.current = window.setInterval(() => {
            cursor += WORDS_PER_TICK * 2; // words and their separators
            const partial = words.slice(0, cursor).join("");

            if (cursor >= words.length) {
              clearTimers();
              commit(question, STREAMED_ANSWER.content);
              return;
            }
            setStreaming((s) => (s ? { ...s, partial } : s));
          }, TYPE_INTERVAL_MS);
        }, STEP_DELAYS[STEP_DELAYS.length - 1].at),
      );
    },
    [clearTimers, commit],
  );

  const stop = useCallback(() => {
    clearTimers();
    setStreaming((s) => {
      if (s) commit(s.question, s.partial || "_Generation stopped before an answer was produced._");
      return null;
    });
  }, [clearTimers, commit]);

  function loadConversation(id: string) {
    clearTimers();
    setStreaming(null);
    setMessages(THREAD);
    setActiveChatId(id);
    setActiveCitation(null);
    setDraft("");
    setDrawerOpen(false);
  }

  function newChat() {
    clearTimers();
    setStreaming(null);
    setMessages([]);
    setActiveChatId(null);
    setActiveCitation(null);
    setDraft("");
    setDrawerOpen(false);
  }

  function handleCitation(messageId: string, source: Source) {
    setActiveCitation((current) =>
      current?.messageId === messageId && current.sourceId === source.id
        ? null
        : { messageId, sourceId: source.id },
    );
  }

  // Ctrl/Cmd+B toggles the sidebar, as documented in Settings → Shortcuts.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        if (isMobile) setDrawerOpen((v) => !v);
        else setCollapsed((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isMobile]);

  const hasThread = messages.length > 0 || streaming !== null;

  // The header takes its title from the question that opened the conversation.
  const firstQuestion = messages.find((m) => m.role === "user")?.content;
  const title = firstQuestion ?? streaming?.question ?? "New conversation";

  const sidebarProps = {
    activeChatId,
    onSelectChat: loadConversation,
    onNewChat: newChat,
    onOpenSettings: () => {
      setSettingsOpen(true);
      setDrawerOpen(false);
    },
  };

  return (
    <TooltipPrimitive.Provider delayDuration={350} skipDelayDuration={200}>
      <div className="flex h-screen w-full overflow-hidden bg-background">
        {!isMobile && <Sidebar collapsed={collapsed} {...sidebarProps} />}

        {/* Mobile: the sidebar becomes a slide-over drawer. */}
        {isMobile && drawerOpen && (
          <div className="fixed inset-0 z-40 flex animate-overlay-in">
            <div
              className="absolute inset-0 bg-black/45"
              onClick={() => setDrawerOpen(false)}
              aria-hidden
            />
            <div className="relative h-full animate-[hbl-panel-in_260ms_cubic-bezier(0.32,0.72,0,1)_both]">
              <Sidebar {...sidebarProps} />
            </div>
          </div>
        )}

        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar
            title={title}
            isMobile={isMobile}
            collapsed={collapsed}
            onToggleSidebar={() => (isMobile ? setDrawerOpen(true) : setCollapsed((v) => !v))}
            onNewChat={newChat}
          />

          <div className="hbl-scroll min-h-0 flex-1 overflow-y-auto">
            <div className="flex min-h-full flex-col">
              <div className="flex-1">
                {hasThread ? (
                  <div className="mx-auto w-full max-w-[760px]">
                    <Thread
                      messages={messages}
                      streaming={streaming}
                      activeCitation={activeCitation}
                      onCitationClick={handleCitation}
                    />
                  </div>
                ) : (
                  <EmptyState onPick={send} />
                )}
              </div>

              <Composer
                value={draft}
                onChange={setDraft}
                onSubmit={send}
                streaming={streaming !== null}
                onStop={stop}
                isMobile={isMobile}
              />
            </div>
          </div>
        </div>

        {openSource &&
          (isMobile ? (
            <div className="fixed inset-0 z-40 flex animate-overlay-in justify-end">
              <div
                className="absolute inset-0 bg-black/45"
                onClick={() => setActiveCitation(null)}
                aria-hidden
              />
              <div className="relative h-full w-full max-w-[400px]">
                <SourcePanel source={openSource} onClose={() => setActiveCitation(null)} />
              </div>
            </div>
          ) : (
            <SourcePanel source={openSource} onClose={() => setActiveCitation(null)} />
          ))}

        {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      </div>
    </TooltipPrimitive.Provider>
  );
}
