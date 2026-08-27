import { useMemo, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronRight,
  Database,
  MoreHorizontal,
  Plus,
  Search,
  Settings,
  Trash2,
  User,
} from "lucide-react";
import { HblLogo, HblMark } from "@/components/common/HblMark";
import { IconButton } from "@/components/common/IconButton";
import { cn, shortcutLabel } from "@/lib/utils";
import { MENU_SURFACE, menuItemCls, primaryButtonCls, rowCls } from "@/lib/variants";
import type { Conversation } from "@/types";


/** Only Delete, because only Delete does anything.
    Pin, Rename and Archive were drawn for the mockup and never implemented;
    a menu item that silently does nothing is worse than an absent one. */
function ChatRowMenu({ onDelete }: { onDelete: () => void }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label="Conversation options"
          className={cn(
            "shrink-0 rounded-md p-1 text-hbl-tertiary opacity-0",
            "transition-all duration-180 ease-spring",
            "hover:bg-black/8 hover:text-hbl-primary dark:hover:bg-white/10",
            "group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100",
          )}
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal size={15} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={4} className={cn(MENU_SURFACE, "w-44")}>
          <DropdownMenu.Item className={menuItemCls(undefined, true)} onSelect={onDelete}>
            <Trash2 size={14} /> Delete
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

function ChatRow({
  chat,
  active,
  onSelect,
  onDelete,
}: {
  chat: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(chat.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(chat.id);
        }
      }}
      className={cn(rowCls(active), "cursor-pointer")}
    >
      <span className="min-w-0 flex-1 truncate leading-5">{chat.title}</span>
      <ChatRowMenu onDelete={() => onDelete(chat.id)} />
    </div>
  );
}

function GroupHeading({ children, icon }: { children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 px-1 pb-1.5 pt-1">
      {icon}
      <h2 className="text-[10px] font-semibold uppercase tracking-[0.06em] text-hbl-tertiary">
        {children}
      </h2>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Expanded                                                                   */
/* -------------------------------------------------------------------------- */

function ExpandedSidebar({
  conversations,
  activeChatId,
  onSelectChat,
  onDeleteChat,
  onNewChat,
  onOpenSettings,
  onOpenDocuments,
  documentCount,
}: {
  conversations: Conversation[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  onOpenDocuments: () => void;
  documentCount: number | null;
}) {
  const searchHint = useMemo(() => shortcutLabel("K"), []);
  const [query, setQuery] = useState("");
  const shown = query.trim()
    ? conversations.filter((c) => c.title.toLowerCase().includes(query.trim().toLowerCase()))
    : conversations;

  return (
    <>
      <div className="flex flex-col gap-1 px-4 pb-3.5 pt-4">
        <HblLogo height={22} />
        <p className="truncate pl-0.5 text-xs leading-4 text-hbl-tertiary">RAG Assistant</p>
      </div>

      <div className="px-3 pb-2">
        <button type="button" onClick={onNewChat} className={cn(primaryButtonCls(), "w-full")}>
          <Plus size={16} />
          New chat
        </button>
      </div>

      <div className="px-3 pb-3">
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg border border-border bg-input-background px-2.5 py-2",
            "transition-all duration-180 ease-spring",
            "focus-within:border-hbl-green focus-within:ring-3 focus-within:ring-[var(--hbl-green-ring)]",
          )}
        >
          <Search size={14} className="shrink-0 text-hbl-tertiary" />
          <input
            type="text"
            placeholder="Search chats"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="min-w-0 flex-1 bg-transparent text-sm leading-5 text-hbl-primary outline-none placeholder:text-hbl-tertiary"
          />
          <kbd className="shrink-0 rounded border border-border bg-card px-1.5 py-0.5 font-sans text-[10px] font-medium leading-4 text-hbl-tertiary">
            {searchHint}
          </kbd>
        </div>
      </div>

      <nav className="hbl-scroll min-h-0 flex-1 overflow-y-auto px-3 pb-2">
        {shown.length === 0 ? (
          // The truthful empty state. History is not persisted yet, so a fresh
          // load genuinely has none — and a list of plausible past chats would
          // misrepresent what the product does.
          <p className="px-2 pt-2 text-[12.5px] leading-5 text-hbl-tertiary">
            {query.trim()
              ? `Nothing in this session matches "${query.trim()}".`
              : "Your questions from this session appear here. They are not saved when you close the app."}
          </p>
        ) : (
          <section className="mb-3">
            <GroupHeading>This session</GroupHeading>
            <div className="flex flex-col gap-0.5">
              {shown.map((chat) => (
                <ChatRow
                  key={chat.id}
                  chat={chat}
                  active={chat.id === activeChatId}
                  onSelect={onSelectChat}
                  onDelete={onDeleteChat}
                />
              ))}
            </div>
          </section>
        )}
      </nav>

      <div className="border-t border-border p-3">
        {/* The document library. Not a picker between knowledge bases — there
            is one corpus, and this is where it is added to and removed from. */}
        <button
          type="button"
          onClick={onOpenDocuments}
          className={cn(
            "flex w-full items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-2 text-left",
            "transition-all duration-180 ease-spring outline-none",
            "hover:bg-black/3 active:scale-99 dark:hover:bg-white/4",
            "focus-visible:ring-3 focus-visible:ring-[var(--hbl-green-ring)]",
          )}
        >
          <Database size={14} className="shrink-0 text-hbl-green" />
          <div className="min-w-0 flex-1">
            <p className="text-[10px] uppercase tracking-[0.06em] text-hbl-tertiary">
              Library
            </p>
            <p className="truncate text-[13px] font-medium leading-4 text-hbl-primary">
              {documentCount === null
                ? "Documents"
                : `${documentCount} document${documentCount === 1 ? "" : "s"}`}
            </p>
          </div>
          <ChevronRight size={14} className="shrink-0 text-hbl-tertiary" />
        </button>

        {/* No account, because there is no sign-in yet — it was deliberately
            deferred until the core worked. A named user with a department
            would imply the app knows who is asking, and it does not. */}
        <div className="mt-2 flex items-center gap-2.5 rounded-lg px-1 py-1.5">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-[#E4EBE7] text-hbl-tertiary dark:bg-[#252B28]">
            <User size={15} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium leading-4 text-hbl-primary">
              Not signed in
            </p>
            <p className="truncate text-[11px] leading-4 text-hbl-tertiary">
              Sign-in is not enabled yet
            </p>
          </div>
          <IconButton label="Settings" size="sm" onClick={onOpenSettings}>
            <Settings size={15} />
          </IconButton>
        </div>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  Collapsed rail                                                             */
/* -------------------------------------------------------------------------- */

function CollapsedSidebar({
  onNewChat,
  onOpenSettings,
  onOpenDocuments,
}: {
  onNewChat: () => void;
  onOpenSettings: () => void;
  onOpenDocuments: () => void;
}) {
  return (
    <>
      <div className="flex justify-center px-3 pb-3.5 pt-5">
        <HblMark height={20} />
      </div>

      <div className="flex justify-center px-3 pb-3">
        <IconButton
          label="New chat"
          onClick={onNewChat}
          className="h-9 w-9 bg-hbl-solid text-hbl-on-solid hover:bg-hbl-solid-hover hover:text-hbl-on-solid active:scale-97 dark:hover:bg-hbl-solid-hover"
        >
          <Plus size={17} />
        </IconButton>
      </div>

      <nav className="flex flex-1 flex-col items-center gap-1 px-3">
        <IconButton label="Documents" onClick={onOpenDocuments}>
          <Database size={17} className="text-hbl-green" />
        </IconButton>
      </nav>

      <div className="flex flex-col items-center gap-1 border-t border-border p-3">
        <IconButton label="Documents" onClick={onOpenDocuments}>
          <Database size={17} className="text-hbl-green" />
        </IconButton>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-[#E4EBE7] text-xs font-semibold text-hbl-secondary dark:bg-[#252B28]">
          AR
        </div>
        <IconButton label="Settings" onClick={onOpenSettings}>
          <Settings size={17} />
        </IconButton>
      </div>
    </>
  );
}

/* -------------------------------------------------------------------------- */

export interface SidebarProps {
  conversations: Conversation[];
  activeChatId: string | null;
  onSelectChat: (id: string) => void;
  onDeleteChat: (id: string) => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  onOpenDocuments: () => void;
  documentCount: number | null;
  collapsed?: boolean;
}

export function Sidebar({ collapsed = false, ...props }: SidebarProps) {
  return (
    <aside
      className={cn(
        "relative flex h-full shrink-0 flex-col overflow-hidden border-r border-border bg-sidebar",
        // Width animates; the icons stay anchored because their column keeps
        // its own padding and the labels cross-fade independently.
        "transition-[width] duration-260 ease-spring",
        // Explicit pixels, not rem: the root font size is 15px and the reader
        // can change it in Settings, which would otherwise resize the sidebar.
        collapsed ? "w-[68px]" : "w-[280px]",
      )}
    >
      {/* Both trees stay mounted so the label fade and the width change run
          together rather than one after the other. */}
      <div
        className={cn(
          "flex h-full w-[280px] flex-col transition-opacity duration-180 ease-spring",
          collapsed && "pointer-events-none absolute opacity-0",
        )}
        aria-hidden={collapsed}
      >
        <ExpandedSidebar {...props} />
      </div>

      {collapsed && (
        <div className="flex h-full w-[68px] flex-col animate-overlay-in">
          <CollapsedSidebar
            onNewChat={props.onNewChat}
            onOpenSettings={props.onOpenSettings}
            onOpenDocuments={props.onOpenDocuments}
          />
        </div>
      )}
    </aside>
  );
}
