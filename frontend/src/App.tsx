import { useCallback, useEffect, useRef, useState } from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { Composer } from "@/components/chat/Composer";
import { EmptyState } from "@/components/chat/EmptyState";
import { Thread, type StreamingState } from "@/components/chat/Thread";
import type { RetrievalStep } from "@/components/chat/RetrievalStepper";
import { DocumentsModal } from "@/components/documents/DocumentsModal";
import { SettingsModal } from "@/components/settings/SettingsModal";
import { SourcePanel } from "@/components/sources/SourcePanel";
import { THREAD } from "@/data/mock";
import { askQuestion, listDocuments, type AnswerAudit } from "@/lib/api";
import { useIsMobile } from "@/lib/useMediaQuery";
import type { ActiveCitation, AssistantMessage, Message, Source } from "@/types";

/**
 * A note the reader needs that the answer itself did not give them.
 *
 * The backend reports, separately from the text, when the model cited a
 * superseded edition or invented a citation. Both have happened repeatedly and
 * neither is visible in the prose — which is exactly why they are appended
 * here rather than left to the model to mention.
 */
function auditNote(audit: AnswerAudit): string {
  const notes: string[] = [];
  if (audit.superseded.length > 0) {
    const which = audit.superseded.map((n) => `[${n}]`).join(" ");
    notes.push(
      `**Superseded sources cited: ${which}.** A newer edition of that policy is also indexed — check the current one before acting on this.`,
    );
  }
  if (audit.invented.length > 0) {
    notes.push(
      `**${audit.invented.length} citation(s) referred to sources that were never retrieved, and were removed.** Treat the surrounding claims with care.`,
    );
  }
  return notes.length > 0 ? `\n\n---\n\n${notes.join("\n\n")}` : "";
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<ActiveCitation | null>(null);
  const [draft, setDraft] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);
  /** null until the backend has answered — the sidebar says "Documents" rather
      than "0 documents", which would read as an empty library. */
  const [documentCount, setDocumentCount] = useState<number | null>(null);

  const isMobile = useIsMobile();
  /** Aborts the in-flight answer — on Stop, and on unmount. */
  const inFlight = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    inFlight.current?.abort();
    inFlight.current = null;
  }, []);

  useEffect(() => abort, [abort]);

  // Refreshed when the library closes, because that is when it may have
  // changed. Failure is silent: the count is a convenience, and the modal
  // reports a backend that is down far better than a sidebar label can.
  const refreshCount = useCallback(() => {
    listDocuments()
      .then((docs) => setDocumentCount(docs.length))
      .catch(() => setDocumentCount(null));
  }, []);

  useEffect(refreshCount, [refreshCount]);

  const openSource =
    activeCitation === null
      ? null
      : (messages
          .filter((m): m is AssistantMessage => m.role === "assistant")
          .find((m) => m.id === activeCitation.messageId)
          ?.sources.find((s) => s.id === activeCitation.sourceId) ?? null);

  /** Commits a finished (or stopped) answer into the thread. */
  const commit = useCallback((question: string, content: string, sources: Source[]) => {
    const stamp = Date.now();
    setMessages((prev) => [
      ...prev,
      { id: `u-${stamp}`, role: "user", content: question },
      { id: `a-${stamp}`, role: "assistant", content, sources },
    ]);
    setStreaming(null);
  }, []);

  /**
   * Asks the backend and renders the answer as it is written.
   *
   * The stepper and the citation pills are driven by the stream's own events
   * rather than by timers: `sources` always arrives before the first `delta`,
   * so a `[1]` in the opening sentence has something to point at.
   *
   * Answers are slow — a CPU-only machine takes minutes — which is why the
   * partial text is committed on every delta rather than batched.
   */
  const send = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (!trimmed) return;

      abort();
      const controller = new AbortController();
      inFlight.current = controller;

      setDraft("");
      setActiveCitation(null);
      setActiveChatId((id) => id ?? "c1");
      setStreaming({
        question: trimmed,
        step: "searching",
        partial: "",
        documentCount: 0,
        sourceCount: 0,
        sources: [],
      });

      // Held outside React state so the final commit sees them without
      // depending on a re-render having landed first.
      let sources: Source[] = [];
      let answer = "";

      void askQuestion(
        trimmed,
        {
          onStep: (step) => setStreaming((s) => (s ? { ...s, step: step as RetrievalStep } : s)),
          onSources: (incoming, documentCount) => {
            sources = incoming;
            setStreaming((s) =>
              s ? { ...s, sources: incoming, sourceCount: incoming.length, documentCount } : s,
            );
          },
          onDelta: (text) => {
            answer += text;
            setStreaming((s) => (s ? { ...s, partial: answer } : s));
          },
          onDone: (audit) => {
            inFlight.current = null;
            commit(trimmed, answer + auditNote(audit), sources);
          },
          onError: (message) => {
            inFlight.current = null;
            // Whatever arrived is real and worth keeping; the failure is
            // appended rather than replacing it.
            const body = answer ? `${answer}\n\n---\n\n**${message}**` : `**${message}**`;
            commit(trimmed, body, sources);
          },
        },
        controller.signal,
      );
    },
    [abort, commit],
  );

  const stop = useCallback(() => {
    abort();
    setStreaming((s) => {
      if (s) {
        commit(
          s.question,
          s.partial || "_Stopped before an answer was produced._",
          s.sources,
        );
      }
      return null;
    });
  }, [abort, commit]);

  function loadConversation(id: string) {
    abort();
    setStreaming(null);
    setMessages(THREAD);
    setActiveChatId(id);
    setActiveCitation(null);
    setDraft("");
    setDrawerOpen(false);
  }

  function newChat() {
    abort();
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
    onOpenDocuments: () => {
      setDocumentsOpen(true);
      setDrawerOpen(false);
    },
    documentCount,
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

        {documentsOpen && (
          <DocumentsModal
            onClose={() => {
              setDocumentsOpen(false);
              refreshCount();
            }}
          />
        )}

        {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      </div>
    </TooltipPrimitive.Provider>
  );
}
