import { Menu, Moon, PanelLeft, PanelLeftClose, Plus, Sun } from "lucide-react";
import { IconButton } from "@/components/common/IconButton";
import { useSettings } from "@/components/settings/SettingsProvider";

export function TopBar({
  title,
  isMobile,
  collapsed,
  onToggleSidebar,
  onNewChat,
}: {
  title: string;
  isMobile: boolean;
  collapsed: boolean;
  onToggleSidebar: () => void;
  onNewChat: () => void;
}) {
  const { theme, toggleTheme } = useSettings();

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border bg-background/80 px-3 backdrop-blur-xl sm:px-5">
      {isMobile ? (
        <IconButton label="Open menu" onClick={onToggleSidebar}>
          <Menu size={18} />
        </IconButton>
      ) : (
        <IconButton
          label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={onToggleSidebar}
          className="-ml-1.5 mr-1"
        >
          {collapsed ? <PanelLeft size={17} /> : <PanelLeftClose size={17} />}
        </IconButton>
      )}

      <h1 className="min-w-0 flex-1 truncate text-[15px] font-medium leading-6 text-hbl-primary">
        {title}
      </h1>

      {isMobile ? (
        <IconButton label="New chat" onClick={onNewChat}>
          <Plus size={18} />
        </IconButton>
      ) : (
        <>
          <div className="flex shrink-0 items-center gap-0.5">
            <IconButton
              label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </IconButton>
          </div>
        </>
      )}
    </header>
  );
}
