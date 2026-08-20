import { HblAvatar } from "@/components/common/HblMark";
import { AnswerActions } from "@/components/chat/AnswerActions";
import { CARET_TOKEN, Markdown } from "@/components/chat/Markdown";
import { RetrievalStepper, type RetrievalStep } from "@/components/chat/RetrievalStepper";
import { SourceSkeletons } from "@/components/chat/SourceSkeletons";
import { SourcesRow } from "@/components/chat/SourcesRow";
import type { ActiveCitation, AssistantMessage, Message, Source, UserMessage } from "@/types";

export interface StreamingState {
  /** Question already sent, echoed as a user turn. */
  question: string;
  step: RetrievalStep;
  /** Whatever has arrived of the answer so far. */
  partial: string;
  documentCount: number;
  sourceCount: number;
  /**
   * Sources are known once retrieval finishes, before the text starts arriving,
   * so citation pills can resolve while the answer is still being written.
   */
  sources: Source[];
}

function UserTurn({ message }: { message: UserMessage }) {
  return (
    <div className="flex animate-rise justify-end">
      <div className="max-w-[70%] rounded-xl bg-hbl-solid px-3.5 py-2.5 text-[15px] leading-6 text-hbl-on-solid">
        {message.content}
      </div>
    </div>
  );
}

/**
 * Assistant turns deliberately have no bubble — the answer sits directly on the
 * canvas so a long, structured response reads like a document rather than a
 * chat message.
 */
function AssistantTurn({
  message,
  activeSourceId,
  onCitationClick,
}: {
  message: AssistantMessage;
  activeSourceId: string | null;
  onCitationClick: (messageId: string, source: Source) => void;
}) {
  const handleCitation = (source: Source) => onCitationClick(message.id, source);

  return (
    <div className="flex animate-rise gap-3">
      <HblAvatar size={26} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <Markdown
          content={message.content}
          sources={message.sources}
          activeSourceId={activeSourceId}
          onCitationClick={handleCitation}
        />
        <SourcesRow
          sources={message.sources}
          activeSourceId={activeSourceId}
          onSelect={handleCitation}
        />
        <AnswerActions content={message.content} />
      </div>
    </div>
  );
}

function StreamingTurn({ state }: { state: StreamingState }) {
  return (
    <div className="flex animate-rise gap-3">
      <HblAvatar size={26} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <RetrievalStepper
          step={state.step}
          documentCount={state.documentCount}
          sourceCount={state.sourceCount}
        />

        {state.partial && (
          <Markdown
            content={state.partial + CARET_TOKEN}
            sources={state.step === "composing" ? state.sources : []}
            onCitationClick={() => {}}
          />
        )}

        <SourceSkeletons count={state.sourceCount} />
      </div>
    </div>
  );
}

export function Thread({
  messages,
  streaming,
  activeCitation,
  onCitationClick,
}: {
  messages: Message[];
  streaming: StreamingState | null;
  activeCitation: ActiveCitation | null;
  onCitationClick: (messageId: string, source: Source) => void;
}) {
  return (
    <div className="flex flex-col gap-8 px-4 pb-4 pt-6 sm:px-6">
      {messages.map((message) =>
        message.role === "user" ? (
          <UserTurn key={message.id} message={message} />
        ) : (
          <AssistantTurn
            key={message.id}
            message={message}
            activeSourceId={
              activeCitation?.messageId === message.id ? activeCitation.sourceId : null
            }
            onCitationClick={onCitationClick}
          />
        ),
      )}

      {streaming && (
        <>
          <UserTurn message={{ id: "pending", role: "user", content: streaming.question }} />
          <StreamingTurn state={streaming} />
        </>
      )}
    </div>
  );
}
