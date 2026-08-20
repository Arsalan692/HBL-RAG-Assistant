import { useState } from "react";
import {
  Send, X, ChevronDown, Check, AlertCircle, Info,
  FileText, Settings, LogOut, History, Bookmark, HelpCircle,
  Home, MessageSquare, Paperclip, Plus, User, Bot, Search, Mic,
} from "lucide-react";

// ── Token types ──────────────────────────────────────────────────────────────
type C = {
  canvas: string; surface: string; elevated: string;
  brand: string; brandHover: string; brandDeep: string;
  brandRing: string; brandBg: string; brandText: string;
  textPrimary: string; textSecondary: string; textTertiary: string;
  border: string; borderStrong: string; muted: string;
  shadow: string; isDark: boolean;
};

const L: C = {
  canvas: "#F7F8F7", surface: "#FFFFFF", elevated: "#FFFFFF",
  brand: "#009A49", brandHover: "#00B356", brandDeep: "#00703A",
  brandRing: "rgba(0,154,73,0.4)", brandBg: "#E8F5EE", brandText: "#00703A",
  textPrimary: "#0D0F0E", textSecondary: "#5C6360", textTertiary: "#8A918D",
  border: "rgba(0,0,0,0.08)", borderStrong: "rgba(0,0,0,0.12)",
  muted: "#F0F1F0",
  shadow: "0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06)",
  isDark: false,
};

const D: C = {
  canvas: "#0B0D0C", surface: "#131615", elevated: "#1A1E1C",
  brand: "#22C55E", brandHover: "#4ADE80", brandDeep: "#16A34A",
  brandRing: "rgba(34,197,94,0.4)", brandBg: "#162B1E", brandText: "#22C55E",
  textPrimary: "#F2F4F3", textSecondary: "#A2AAA6", textTertiary: "#6E7671",
  border: "rgba(255,255,255,0.10)", borderStrong: "rgba(255,255,255,0.15)",
  muted: "#1A1E1C",
  shadow: "none",
  isDark: true,
};

// ── Layout atoms ─────────────────────────────────────────────────────────────
function SectionRow({ title, c, children }: { title: string; c: C; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 48 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: c.textTertiary, whiteSpace: "nowrap" }}>
          {title}
        </span>
        <div style={{ flex: 1, height: 1, background: c.border }} />
      </div>
      {children}
    </div>
  );
}

function VRow({ label, c, children }: { label?: string; c: C; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 20 }}>
      {label && <span style={{ fontSize: 11, color: c.textTertiary, fontWeight: 500, display: "block", marginBottom: 10 }}>{label}</span>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "flex-end" }}>{children}</div>
    </div>
  );
}

function VCell({ label, c, children }: { label: string; c: C; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      {children}
      <span style={{ fontSize: 10, color: c.textTertiary, letterSpacing: "0.04em", fontWeight: 500 }}>{label}</span>
    </div>
  );
}

// ── Color swatch ──────────────────────────────────────────────────────────────
function Swatch({ hex, name, c }: { hex: string; name: string; c: C }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
      <div style={{ width: 44, height: 44, borderRadius: 8, background: hex, border: `1px solid ${c.border}`, boxShadow: c.shadow }} />
      <span style={{ fontSize: 9, fontFamily: "monospace", color: c.textTertiary }}>{hex}</span>
      <span style={{ fontSize: 10, color: c.textSecondary, textAlign: "center", maxWidth: 56 }}>{name}</span>
    </div>
  );
}

// ── Button variants ───────────────────────────────────────────────────────────
function BtnPrimary({ state = "default", c }: { state?: string; c: C }) {
  const bg =
    state === "hover" ? c.brandHover :
    state === "pressed" ? c.brandDeep :
    state === "disabled" ? (c.isDark ? "rgba(34,197,94,0.2)" : "rgba(0,154,73,0.25)") :
    c.brand;
  const box = state === "focused" ? `0 0 0 2px ${c.canvas}, 0 0 0 4px ${c.brandRing}` : undefined;
  return (
    <button style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "8px 16px", borderRadius: 8,
      background: bg, color: "#FFFFFF",
      fontSize: 15, fontWeight: 500, lineHeight: "24px",
      border: "none", cursor: state === "disabled" ? "not-allowed" : "pointer",
      opacity: state === "disabled" ? 0.55 : 1,
      boxShadow: box, fontFamily: "inherit", outline: "none", transition: "all 0.15s",
    }}>
      Send Message
    </button>
  );
}

function BtnSecondary({ state = "default", c }: { state?: string; c: C }) {
  const bg =
    state === "hover" ? (c.isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.03)") :
    state === "pressed" ? (c.isDark ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.07)") :
    state === "disabled" ? c.muted :
    c.surface;
  const box = state === "focused" ? `0 0 0 2px ${c.canvas}, 0 0 0 4px ${c.brandRing}` : undefined;
  return (
    <button style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "8px 16px", borderRadius: 8,
      background: bg,
      color: state === "disabled" ? c.textTertiary : c.textPrimary,
      fontSize: 15, fontWeight: 500, lineHeight: "24px",
      border: `1px solid ${c.border}`,
      cursor: state === "disabled" ? "not-allowed" : "pointer",
      boxShadow: box, fontFamily: "inherit", outline: "none", transition: "all 0.15s",
    }}>
      New Chat
    </button>
  );
}

function BtnGhost({ state = "default", c }: { state?: string; c: C }) {
  const bg =
    state === "hover" ? (c.isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)") :
    state === "pressed" ? (c.isDark ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.08)") :
    "transparent";
  return (
    <button style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "8px 16px", borderRadius: 8,
      background: bg,
      color: state === "disabled" ? c.textTertiary : c.textPrimary,
      fontSize: 15, fontWeight: 500, lineHeight: "24px",
      border: "none", cursor: state === "disabled" ? "not-allowed" : "pointer",
      fontFamily: "inherit", outline: "none", transition: "all 0.15s",
    }}>
      Cancel
    </button>
  );
}

function BtnIcon({ state = "default", c, children }: { state?: string; c: C; children: React.ReactNode }) {
  const bg =
    state === "hover" ? (c.isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.05)") :
    state === "pressed" ? (c.isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.08)") :
    "transparent";
  const color =
    state === "active" ? c.brand :
    state === "disabled" ? c.textTertiary :
    c.textSecondary;
  return (
    <button style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 36, height: 36, borderRadius: 8,
      background: bg, color,
      border: "none", cursor: state === "disabled" ? "not-allowed" : "pointer",
      fontFamily: "inherit", outline: "none", transition: "all 0.15s",
    }}>
      {children}
    </button>
  );
}

// ── Input ─────────────────────────────────────────────────────────────────────
function InputField({ state = "default", c }: { state?: string; c: C }) {
  const borderColor =
    state === "focused" ? c.brand :
    state === "error" ? "#C0392B" :
    c.border;
  const box = state === "focused" ? `0 0 0 3px ${c.brandRing}` : undefined;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      padding: "10px 12px", borderRadius: 8, width: 240,
      background: state === "disabled" ? c.muted : c.surface,
      border: `1px solid ${borderColor}`,
      boxShadow: box, transition: "all 0.15s",
    }}>
      <Search size={15} style={{ color: c.textTertiary, flexShrink: 0 }} />
      <span style={{
        fontSize: 15, lineHeight: "24px", flex: 1,
        color: (state === "default" || state === "disabled") ? c.textTertiary : c.textPrimary,
      }}>
        {state === "default" || state === "disabled" ? "Search documents…" : "Annual Report 2024"}
      </span>
      {state === "error" && <AlertCircle size={15} style={{ color: "#C0392B", flexShrink: 0 }} />}
    </div>
  );
}

// ── Composer ──────────────────────────────────────────────────────────────────
function Composer({ c }: { c: C }) {
  return (
    <div style={{
      border: `1px solid ${c.border}`, borderRadius: 12,
      background: c.surface, boxShadow: c.shadow,
      width: 460, overflow: "hidden",
    }}>
      <textarea
        readOnly
        defaultValue="What were HBL's total non-performing loans in Q3 2024?"
        style={{
          width: "100%", border: "none", outline: "none", resize: "none",
          padding: "12px 16px 8px", fontSize: 15, lineHeight: "24px",
          color: c.textPrimary, background: "transparent",
          fontFamily: "inherit", minHeight: 76, boxSizing: "border-box",
        }}
      />
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "8px 10px 10px 10px", borderTop: `1px solid ${c.border}`,
      }}>
        <div style={{ display: "flex", gap: 0 }}>
          {[<Paperclip size={15} />, <Mic size={15} />].map((icon, i) => (
            <button key={i} style={{
              border: "none", background: "transparent", cursor: "pointer",
              padding: "6px 7px", borderRadius: 6, color: c.textTertiary, lineHeight: 0,
            }}>
              {icon}
            </button>
          ))}
        </div>
        <button style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 32, height: 32, borderRadius: 8,
          background: c.brand, color: "#FFF",
          border: "none", cursor: "pointer",
        }}>
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}

// ── Chip ──────────────────────────────────────────────────────────────────────
function Chip({ state = "default", label, c }: { state?: string; label: string; c: C }) {
  const bg =
    state === "selected" ? c.brandBg :
    state === "hover" ? (c.isDark ? "rgba(255,255,255,0.07)" : "rgba(0,0,0,0.05)") :
    c.muted;
  const textColor = state === "selected" ? c.brandText : c.textSecondary;
  const border = state === "selected" ? `1px solid ${c.brand}` : "1px solid transparent";
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "5px 12px", borderRadius: 999,
      background: bg, color: textColor, border,
      fontSize: 13, fontWeight: 500, lineHeight: "18px",
      cursor: "pointer", userSelect: "none", transition: "all 0.15s",
    }}>
      {label}
      {state === "dismissible" && <X size={11} style={{ marginLeft: 2 }} />}
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────────
function Badge({ variant = "neutral", label, c }: { variant?: string; label: string; c: C }) {
  const map: Record<string, { bg: string; text: string }> = {
    neutral: { bg: c.muted, text: c.textSecondary },
    success: { bg: c.brandBg, text: c.brandText },
    warning: { bg: c.isDark ? "rgba(234,179,8,0.15)" : "#FEF3C7", text: c.isDark ? "#FACC15" : "#92400E" },
    error: { bg: c.isDark ? "rgba(239,68,68,0.15)" : "#FEE2E2", text: c.isDark ? "#F87171" : "#991B1B" },
    info: { bg: c.isDark ? "rgba(59,130,246,0.15)" : "#DBEAFE", text: c.isDark ? "#93C5FD" : "#1D4ED8" },
  };
  const s = map[variant] || map.neutral;
  return (
    <div style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: 999,
      background: s.bg, color: s.text,
      fontSize: 12, fontWeight: 500, lineHeight: "16px",
    }}>
      {label}
    </div>
  );
}

// ── Avatar ────────────────────────────────────────────────────────────────────
function Avatar({ size = 32, name, isBot = false, c }: { size?: number; name?: string; isBot?: boolean; c: C }) {
  const fs = size <= 24 ? 9 : size <= 32 ? 12 : size <= 40 ? 14 : 16;
  const initials = name ? name.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2) : "";
  return (
    <div style={{
      width: size, height: size, borderRadius: "50%",
      background: isBot ? c.brandBg : (c.isDark ? "#252B28" : "#E4EBE7"),
      color: isBot ? c.brandText : c.textSecondary,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: fs, fontWeight: 600, flexShrink: 0,
      border: `1px solid ${c.border}`,
    }}>
      {isBot ? <Bot size={size * 0.44} /> : (initials || <User size={size * 0.5} />)}
    </div>
  );
}

// ── Tooltip ───────────────────────────────────────────────────────────────────
function Tooltip({ c }: { c: C }) {
  const tipBg = c.isDark ? "#2D3330" : "#1A1E1C";
  return (
    <div style={{ position: "relative", display: "inline-flex", flexDirection: "column", alignItems: "center" }}>
      <div style={{
        background: tipBg, color: "#F2F4F3",
        padding: "6px 10px", borderRadius: 8,
        fontSize: 12, lineHeight: "16px",
        boxShadow: "0 4px 16px rgba(0,0,0,0.2)", whiteSpace: "nowrap",
      }}>
        View source document
      </div>
      <div style={{
        width: 0, height: 0,
        borderLeft: "5px solid transparent", borderRight: "5px solid transparent",
        borderTop: `5px solid ${tipBg}`, marginTop: -1,
      }} />
      <button style={{
        marginTop: 6, border: `1px solid ${c.border}`, borderRadius: 8,
        background: c.surface, color: c.textSecondary,
        padding: "6px 12px", fontSize: 13, cursor: "pointer", fontFamily: "inherit",
      }}>
        Source [1]
      </button>
    </div>
  );
}

// ── Dropdown ──────────────────────────────────────────────────────────────────
function Dropdown({ c }: { c: C }) {
  const items: Array<{ icon?: React.ReactNode; label: string; danger?: boolean } | { divider: true }> = [
    { icon: <History size={14} />, label: "Chat History" },
    { icon: <Bookmark size={14} />, label: "Saved Responses" },
    { icon: <FileText size={14} />, label: "Source Documents" },
    { divider: true },
    { icon: <Settings size={14} />, label: "Preferences" },
    { icon: <LogOut size={14} />, label: "Sign Out", danger: true },
  ];
  return (
    <div style={{
      background: c.elevated, border: `1px solid ${c.border}`,
      borderRadius: 12, padding: 4, width: 220,
      boxShadow: c.isDark ? "0 8px 24px rgba(0,0,0,0.5)" : "0 8px 24px rgba(0,0,0,0.10)",
    }}>
      {items.map((item, i) => {
        if ("divider" in item) return <div key={i} style={{ height: 1, background: c.border, margin: "4px 0" }} />;
        return (
          <div
            key={i}
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 10px", borderRadius: 8, cursor: "pointer",
              color: item.danger ? "#C0392B" : c.textPrimary,
              fontSize: 14, lineHeight: "20px", transition: "background 0.1s",
            }}
          >
            <span style={{ color: item.danger ? "#C0392B" : c.textTertiary, lineHeight: 0 }}>{item.icon}</span>
            {item.label}
          </div>
        );
      })}
    </div>
  );
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function Modal({ c }: { c: C }) {
  return (
    <div style={{
      background: c.elevated, border: `1px solid ${c.border}`,
      borderRadius: 16, padding: 24, width: 380,
      boxShadow: c.isDark ? "0 24px 64px rgba(0,0,0,0.6)" : "0 24px 64px rgba(0,0,0,0.12)",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <h3 style={{ fontSize: 20, fontWeight: 600, color: c.textPrimary, lineHeight: "28px", letterSpacing: "-0.01em" }}>
          Clear Chat History
        </h3>
        <button style={{
          border: "none",
          background: c.isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)",
          color: c.textSecondary, cursor: "pointer", padding: 5, borderRadius: 6, lineHeight: 0,
        }}>
          <X size={14} />
        </button>
      </div>
      <p style={{ fontSize: 15, color: c.textSecondary, lineHeight: "24px", marginBottom: 20 }}>
        This will permanently delete all conversations. This action cannot be undone.
      </p>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button style={{
          padding: "8px 16px", borderRadius: 8, border: `1px solid ${c.border}`,
          background: c.surface, color: c.textPrimary,
          fontSize: 15, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
        }}>
          Cancel
        </button>
        <button style={{
          padding: "8px 16px", borderRadius: 8, border: "none",
          background: "#C0392B", color: "#FFF",
          fontSize: 15, fontWeight: 500, cursor: "pointer", fontFamily: "inherit",
        }}>
          Clear History
        </button>
      </div>
    </div>
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function Toast({ variant = "success", c }: { variant?: string; c: C }) {
  const map: Record<string, { icon: React.ReactNode; iconBg: string; iconColor: string; msg: string }> = {
    success: { icon: <Check size={13} />, iconBg: c.brandBg, iconColor: c.brandText, msg: "Response saved to history" },
    error: { icon: <AlertCircle size={13} />, iconBg: c.isDark ? "rgba(239,68,68,0.15)" : "#FEE2E2", iconColor: c.isDark ? "#F87171" : "#991B1B", msg: "Failed to load documents" },
    info: { icon: <Info size={13} />, iconBg: c.isDark ? "rgba(59,130,246,0.15)" : "#DBEAFE", iconColor: c.isDark ? "#93C5FD" : "#1D4ED8", msg: "Generating response…" },
  };
  const cfg = map[variant] || map.success;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "12px 14px", borderRadius: 12, width: 300,
      background: c.elevated, border: `1px solid ${c.border}`,
      boxShadow: c.isDark ? "0 4px 16px rgba(0,0,0,0.4)" : "0 4px 16px rgba(0,0,0,0.08)",
    }}>
      <div style={{
        width: 24, height: 24, borderRadius: 6, flexShrink: 0,
        background: cfg.iconBg, color: cfg.iconColor,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        {cfg.icon}
      </div>
      <span style={{ fontSize: 13, color: c.textPrimary, lineHeight: "18px", flex: 1 }}>{cfg.msg}</span>
      <button style={{ border: "none", background: "transparent", color: c.textTertiary, cursor: "pointer", lineHeight: 0, padding: 2 }}>
        <X size={13} />
      </button>
    </div>
  );
}

// ── Segmented Control ─────────────────────────────────────────────────────────
function SegControl({ c }: { c: C }) {
  const [active, setActive] = useState(0);
  const tabs = ["All Sources", "Policy", "Reports"];
  return (
    <div style={{ display: "inline-flex", padding: 3, borderRadius: 10, background: c.muted, gap: 2 }}>
      {tabs.map((tab, i) => (
        <button
          key={tab}
          onClick={() => setActive(i)}
          style={{
            padding: "6px 14px", borderRadius: 8, border: "none",
            background: active === i ? c.surface : "transparent",
            color: active === i ? c.textPrimary : c.textSecondary,
            fontSize: 13, fontWeight: active === i ? 500 : 400,
            cursor: "pointer", fontFamily: "inherit",
            boxShadow: active === i && !c.isDark ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
            transition: "all 0.15s",
          }}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}

// ── Toggle ────────────────────────────────────────────────────────────────────
function Toggle({ on: defaultOn = false, disabled = false, c }: { on?: boolean; disabled?: boolean; c: C }) {
  const [on, setOn] = useState(defaultOn);
  return (
    <button
      onClick={() => !disabled && setOn((v) => !v)}
      style={{
        width: 44, height: 26, borderRadius: 999, border: "none",
        background: on ? c.brand : (c.isDark ? "#3A4040" : "#C8CCC9"),
        cursor: disabled ? "not-allowed" : "pointer",
        position: "relative", padding: 0,
        opacity: disabled ? 0.4 : 1, transition: "background 0.2s",
      }}
    >
      <div style={{
        position: "absolute", top: 3, left: on ? 21 : 3,
        width: 20, height: 20, borderRadius: "50%",
        background: "#FFFFFF",
        boxShadow: "0 1px 3px rgba(0,0,0,0.25)",
        transition: "left 0.2s",
      }} />
    </button>
  );
}

// ── Sidebar Item ──────────────────────────────────────────────────────────────
function SidebarItem({ state = "default", icon, label, badge, c }: {
  state?: string; icon: React.ReactNode; label: string; badge?: number; c: C;
}) {
  const bg =
    state === "active" ? (c.isDark ? "rgba(34,197,94,0.08)" : c.brandBg) :
    state === "hover" ? (c.isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.04)") :
    "transparent";
  const iconColor = state === "active" ? c.brand : state === "disabled" ? c.textTertiary : c.textTertiary;
  const textColor = state === "active" ? c.brandText : state === "disabled" ? c.textTertiary : c.textPrimary;
  const leftBorder = state === "active" ? `2px solid ${c.brand}` : "2px solid transparent";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "9px 14px 9px 12px", borderRadius: 8,
      background: bg, borderLeft: leftBorder,
      cursor: state === "disabled" ? "not-allowed" : "pointer",
      transition: "all 0.15s", userSelect: "none",
    }}>
      <span style={{ color: iconColor, lineHeight: 0 }}>{icon}</span>
      <span style={{ fontSize: 14, fontWeight: state === "active" ? 500 : 400, color: textColor, flex: 1, lineHeight: "20px" }}>
        {label}
      </span>
      {badge !== undefined && (
        <div style={{
          minWidth: 18, height: 18, borderRadius: 999,
          background: c.brand, color: "#FFF",
          fontSize: 10, fontWeight: 600,
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "0 5px",
        }}>
          {badge}
        </div>
      )}
    </div>
  );
}

// ── Message Bubbles ───────────────────────────────────────────────────────────
function UserBubble({ c }: { c: C }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <div style={{
        maxWidth: 340, padding: "10px 14px",
        borderRadius: "12px 12px 4px 12px",
        background: c.brand, color: "#FFFFFF",
        fontSize: 15, lineHeight: "24px",
      }}>
        What is HBL's current Capital Adequacy Ratio?
      </div>
    </div>
  );
}

function AssistantBubble({ c }: { c: C }) {
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
      <Avatar size={32} isBot c={c} />
      <div>
        <div style={{
          display: "inline-block", padding: "10px 14px",
          borderRadius: "4px 12px 12px 12px",
          background: c.surface, border: `1px solid ${c.border}`,
          fontSize: 15, lineHeight: "24px", color: c.textPrimary,
          boxShadow: c.shadow, maxWidth: 380,
        }}>
          HBL maintained a Capital Adequacy Ratio of{" "}
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 3,
            background: c.brandBg, color: c.brandText,
            padding: "1px 6px", borderRadius: 4,
            fontSize: 13, fontWeight: 500, cursor: "pointer",
          }}>
            19.8%
            <sup style={{ fontSize: 9, fontWeight: 700 }}>1</sup>
          </span>
          {" "}as of Q3 2024, exceeding the SBP minimum requirement of 10.5%.
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
          {["Annual Report 2024 · p.47", "BSCS Filing Q3"].map((src, i) => (
            <div key={i} style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "3px 8px", borderRadius: 6,
              background: c.muted, border: `1px solid ${c.border}`,
              fontSize: 11, color: c.textSecondary, cursor: "pointer",
            }}>
              <FileText size={10} style={{ color: c.textTertiary }} />
              {src}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Skeleton loader ───────────────────────────────────────────────────────────
function Skeleton({ c }: { c: C }) {
  const bar = (w: string | number, h = 11, r = 5) => (
    <div style={{
      width: w, height: h, borderRadius: r,
      background: c.isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)",
    }} />
  );
  return (
    <div style={{ display: "flex", gap: 10, alignItems: "flex-start", width: 360 }}>
      <div style={{
        width: 32, height: 32, borderRadius: "50%",
        background: c.isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)",
        flexShrink: 0,
      }} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, paddingTop: 4 }}>
        {bar("72%")} {bar("88%")} {bar("54%")}
      </div>
    </div>
  );
}

// ── Source Card ───────────────────────────────────────────────────────────────
function SourceCard({ c }: { c: C }) {
  return (
    <div style={{
      padding: "14px 16px", borderRadius: 12, border: `1px solid ${c.border}`,
      background: c.surface, boxShadow: c.shadow, width: 280, cursor: "pointer",
    }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{
          width: 34, height: 34, borderRadius: 8, flexShrink: 0,
          background: c.brandBg, display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <FileText size={16} style={{ color: c.brandText }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{ fontSize: 13, fontWeight: 500, color: c.textPrimary, lineHeight: "18px", marginBottom: 2 }}>
            HBL Annual Report 2024
          </p>
          <p style={{ fontSize: 11, color: c.textTertiary, lineHeight: "16px", marginBottom: 6 }}>
            Page 47 — Capital Adequacy
          </p>
          <p style={{
            fontSize: 12, color: c.textSecondary, lineHeight: "16px",
            display: "-webkit-box", WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical" as const, overflow: "hidden",
          }}>
            "The Bank maintained a strong capital base with CAR at 19.8%, well above the regulatory minimum…"
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Citation Pill ─────────────────────────────────────────────────────────────
function CitationPill({ num, label, active, c }: { num: number; label: string; active?: boolean; c: C }) {
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 10px 4px 5px", borderRadius: 999,
      border: `1px solid ${active ? c.brand : c.border}`,
      background: active ? c.brandBg : c.surface,
      cursor: "pointer", transition: "all 0.15s",
    }}>
      <span style={{
        width: 17, height: 17, borderRadius: "50%",
        background: active ? c.brand : c.muted,
        color: active ? "#FFF" : c.textTertiary,
        fontSize: 9, fontWeight: 700,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>
        {num}
      </span>
      <span style={{ fontSize: 12, fontWeight: 500, color: active ? c.brandText : c.textSecondary }}>
        {label}
      </span>
    </div>
  );
}

// ── Empty State ───────────────────────────────────────────────────────────────
function EmptyState({ c }: { c: C }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      gap: 12, padding: "32px 24px", textAlign: "center", width: 300,
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: 16,
        background: c.brandBg,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <MessageSquare size={24} style={{ color: c.brandText }} />
      </div>
      <div>
        <p style={{ fontSize: 15, fontWeight: 600, color: c.textPrimary, letterSpacing: "-0.01em", lineHeight: "22px", marginBottom: 4 }}>
          Start a new conversation
        </p>
        <p style={{ fontSize: 13, color: c.textSecondary, lineHeight: "18px" }}>
          Ask anything about HBL policies, financial reports, or compliance documents.
        </p>
      </div>
      <button style={{
        padding: "8px 18px", borderRadius: 8, border: "none",
        background: c.brand, color: "#FFF", fontSize: 13, fontWeight: 500,
        cursor: "pointer", fontFamily: "inherit",
      }}>
        New Chat
      </button>
    </div>
  );
}

// ── Typography showcase ───────────────────────────────────────────────────────
function TypeScale({ c }: { c: C }) {
  const rows = [
    { style: { fontSize: 28, fontWeight: 600, letterSpacing: "-0.01em", lineHeight: "34px" }, spec: "28 / 34 · Semibold · −0.01em", label: "Display", sample: "HBL RAG Assistant" },
    { style: { fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em", lineHeight: "28px" }, spec: "20 / 28 · Semibold · −0.01em", label: "Title", sample: "Capital Adequacy Report" },
    { style: { fontSize: 15, fontWeight: 400, lineHeight: "24px" }, spec: "15 / 24 · Regular", label: "Body", sample: "HBL maintained a CAR of 19.8% as of Q3 2024." },
    { style: { fontSize: 13, fontWeight: 500, lineHeight: "18px" }, spec: "13 / 18 · Medium", label: "Label", sample: "Source Document · Page 47" },
    { style: { fontSize: 12, fontWeight: 400, lineHeight: "16px" }, spec: "12 / 16 · Regular", label: "Caption", sample: "Generated 14:32 · HBL Internal Use Only" },
  ];
  const textColors = [c.textPrimary, c.textPrimary, c.textPrimary, c.textSecondary, c.textTertiary];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
          <span style={{ width: 52, fontSize: 10, color: c.textTertiary, fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase", flexShrink: 0 }}>
            {r.label}
          </span>
          <span style={{ ...r.style, color: textColors[i] }}>{r.sample}</span>
          <span style={{ fontSize: 10, color: c.textTertiary, flexShrink: 0, marginLeft: "auto" }}>{r.spec}</span>
        </div>
      ))}
    </div>
  );
}

// ── Radius & Spacing ──────────────────────────────────────────────────────────
function RadiusRow({ c }: { c: C }) {
  const items = [
    { r: 8, label: "8 — Input / Chip" },
    { r: 12, label: "12 — Card / Bubble" },
    { r: 16, label: "16 — Panel / Modal" },
    { r: 999, label: "999 — Pill" },
  ];
  return (
    <div style={{ display: "flex", gap: 20, alignItems: "flex-end" }}>
      {items.map((it) => (
        <div key={it.r} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 60, height: 60, borderRadius: it.r > 30 ? 999 : it.r,
            border: `1px solid ${c.border}`, background: c.surface,
          }} />
          <span style={{ fontSize: 10, color: c.textTertiary, textAlign: "center", maxWidth: 72 }}>{it.label}</span>
        </div>
      ))}
    </div>
  );
}

function SpacingRow({ c }: { c: C }) {
  const steps = [4, 8, 12, 16, 24, 32, 48];
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
      {steps.map((s) => (
        <div key={s} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
          <div style={{ width: s, height: s, borderRadius: 3, background: c.brand, opacity: 0.6 }} />
          <span style={{ fontSize: 9, color: c.textTertiary }}>{s}</span>
        </div>
      ))}
    </div>
  );
}

// ── Full sheet ────────────────────────────────────────────────────────────────
function Sheet({ c }: { c: C }) {
  return (
    <div style={{ background: c.canvas, borderRadius: 20, padding: 48 }}>
      {/* Header */}
      <div style={{ marginBottom: 44, paddingBottom: 32, borderBottom: `1px solid ${c.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: c.brand, display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: 15, color: "#FFF", fontWeight: 700, fontFamily: "inherit" }}>H</span>
          </div>
          <span style={{ fontSize: 12, fontWeight: 600, color: c.textTertiary, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Habib Bank Limited
          </span>
        </div>
        <h1 style={{ fontSize: 28, fontWeight: 600, color: c.textPrimary, letterSpacing: "-0.01em", lineHeight: "34px", marginBottom: 6 }}>
          HBL RAG Chatbot — Design System
        </h1>
        <p style={{ fontSize: 15, color: c.textSecondary, lineHeight: "24px" }}>
          {c.isDark ? "Dark Mode" : "Light Mode"} · Component Library v1.0 · Inter · Internal Use Only
        </p>
      </div>

      {/* Color Tokens */}
      <SectionRow title="Color Tokens" c={c}>
        <VRow label="Brand" c={c}>
          <Swatch hex={c.brand} name="Brand" c={c} />
          <Swatch hex={c.brandHover} name="Brand Hover" c={c} />
          <Swatch hex={c.brandDeep} name="Brand Deep" c={c} />
          <Swatch hex={c.brandBg} name="Brand BG" c={c} />
          <Swatch hex={c.brandRing} name="Focus Ring" c={c} />
        </VRow>
        <VRow label="Surface" c={c}>
          <Swatch hex={c.canvas} name="Canvas" c={c} />
          <Swatch hex={c.surface} name="Surface" c={c} />
          <Swatch hex={c.elevated} name="Elevated" c={c} />
          <Swatch hex={c.muted} name="Muted" c={c} />
        </VRow>
        <VRow label="Text" c={c}>
          <Swatch hex={c.textPrimary} name="Text Primary" c={c} />
          <Swatch hex={c.textSecondary} name="Text Secondary" c={c} />
          <Swatch hex={c.textTertiary} name="Text Tertiary" c={c} />
        </VRow>
      </SectionRow>

      {/* Typography */}
      <SectionRow title="Typography — Inter" c={c}>
        <TypeScale c={c} />
      </SectionRow>

      {/* Radii & Spacing */}
      <SectionRow title="Radii & Spacing Scale" c={c}>
        <VRow label="Border Radius" c={c}>
          <RadiusRow c={c} />
        </VRow>
        <VRow label="Spacing · 4 8 12 16 24 32 48" c={c}>
          <SpacingRow c={c} />
        </VRow>
      </SectionRow>

      {/* Buttons */}
      <SectionRow title="Button" c={c}>
        <VRow label="Primary" c={c}>
          {(["default", "hover", "pressed", "disabled", "focused"] as const).map((s) => (
            <VCell key={s} label={s} c={c}><BtnPrimary state={s} c={c} /></VCell>
          ))}
        </VRow>
        <VRow label="Secondary" c={c}>
          {(["default", "hover", "pressed", "disabled", "focused"] as const).map((s) => (
            <VCell key={s} label={s} c={c}><BtnSecondary state={s} c={c} /></VCell>
          ))}
        </VRow>
        <VRow label="Ghost" c={c}>
          {(["default", "hover", "pressed", "disabled"] as const).map((s) => (
            <VCell key={s} label={s} c={c}><BtnGhost state={s} c={c} /></VCell>
          ))}
        </VRow>
        <VRow label="Icon Button" c={c}>
          <VCell label="default" c={c}><BtnIcon state="default" c={c}><Settings size={16} /></BtnIcon></VCell>
          <VCell label="hover" c={c}><BtnIcon state="hover" c={c}><Search size={16} /></BtnIcon></VCell>
          <VCell label="active" c={c}><BtnIcon state="active" c={c}><Home size={16} /></BtnIcon></VCell>
          <VCell label="pressed" c={c}><BtnIcon state="pressed" c={c}><Plus size={16} /></BtnIcon></VCell>
          <VCell label="disabled" c={c}><BtnIcon state="disabled" c={c}><HelpCircle size={16} /></BtnIcon></VCell>
        </VRow>
      </SectionRow>

      {/* Input */}
      <SectionRow title="Input" c={c}>
        <VRow c={c}>
          {(["default", "focused", "filled", "error", "disabled"] as const).map((s) => (
            <VCell key={s} label={s} c={c}><InputField state={s} c={c} /></VCell>
          ))}
        </VRow>
      </SectionRow>

      {/* Composer */}
      <SectionRow title="Composer" c={c}>
        <VRow c={c}><Composer c={c} /></VRow>
      </SectionRow>

      {/* Chips & Badges */}
      <SectionRow title="Chip & Badge" c={c}>
        <VRow label="Chips" c={c}>
          <VCell label="default" c={c}><Chip state="default" label="Annual Reports" c={c} /></VCell>
          <VCell label="hover" c={c}><Chip state="hover" label="Policy Docs" c={c} /></VCell>
          <VCell label="selected" c={c}><Chip state="selected" label="Compliance" c={c} /></VCell>
          <VCell label="dismissible" c={c}><Chip state="dismissible" label="Q3 2024" c={c} /></VCell>
        </VRow>
        <VRow label="Badges" c={c}>
          <VCell label="neutral" c={c}><Badge variant="neutral" label="Internal" c={c} /></VCell>
          <VCell label="success" c={c}><Badge variant="success" label="Verified" c={c} /></VCell>
          <VCell label="warning" c={c}><Badge variant="warning" label="Pending" c={c} /></VCell>
          <VCell label="error" c={c}><Badge variant="error" label="Failed" c={c} /></VCell>
          <VCell label="info" c={c}><Badge variant="info" label="Updated" c={c} /></VCell>
        </VRow>
      </SectionRow>

      {/* Avatar */}
      <SectionRow title="Avatar" c={c}>
        <VRow c={c}>
          <VCell label="24 · user" c={c}><Avatar size={24} name="Ahmad Raza" c={c} /></VCell>
          <VCell label="32 · user" c={c}><Avatar size={32} name="Sana Khan" c={c} /></VCell>
          <VCell label="40 · user" c={c}><Avatar size={40} name="Omar Farooq" c={c} /></VCell>
          <VCell label="48 · user" c={c}><Avatar size={48} name="Nadia Ali" c={c} /></VCell>
          <VCell label="32 · bot" c={c}><Avatar size={32} isBot c={c} /></VCell>
          <VCell label="40 · bot" c={c}><Avatar size={40} isBot c={c} /></VCell>
        </VRow>
      </SectionRow>

      {/* Sidebar */}
      <SectionRow title="Sidebar Item" c={c}>
        <div style={{ width: 248, display: "flex", flexDirection: "column", gap: 1, background: c.surface, borderRadius: 12, border: `1px solid ${c.border}`, padding: 6 }}>
          <SidebarItem state="active" icon={<MessageSquare size={15} />} label="New Chat" c={c} />
          <SidebarItem state="hover" icon={<History size={15} />} label="History" c={c} />
          <SidebarItem state="default" icon={<Bookmark size={15} />} label="Saved" c={c} />
          <SidebarItem state="default" icon={<FileText size={15} />} label="Documents" badge={3} c={c} />
          <SidebarItem state="disabled" icon={<Settings size={15} />} label="Settings" c={c} />
        </div>
      </SectionRow>

      {/* Controls */}
      <SectionRow title="Segmented Control & Toggle" c={c}>
        <VRow label="Segmented Control" c={c}>
          <SegControl c={c} />
        </VRow>
        <VRow label="Toggle" c={c}>
          <VCell label="off" c={c}><Toggle on={false} c={c} /></VCell>
          <VCell label="on" c={c}><Toggle on={true} c={c} /></VCell>
          <VCell label="disabled off" c={c}><Toggle on={false} disabled c={c} /></VCell>
          <VCell label="disabled on" c={c}><Toggle on={true} disabled c={c} /></VCell>
        </VRow>
      </SectionRow>

      {/* Message Bubbles */}
      <SectionRow title="Message Bubble" c={c}>
        <div style={{ maxWidth: 520, display: "flex", flexDirection: "column", gap: 16 }}>
          <UserBubble c={c} />
          <AssistantBubble c={c} />
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <Avatar size={32} isBot c={c} />
            <div style={{ flex: 1, paddingTop: 8 }}><Skeleton c={c} /></div>
          </div>
        </div>
      </SectionRow>

      {/* Source Card & Citations */}
      <SectionRow title="Source Card & Citation Pill" c={c}>
        <VRow c={c}>
          <SourceCard c={c} />
          <div style={{ display: "flex", flexDirection: "column", gap: 8, justifyContent: "center" }}>
            <CitationPill num={1} label="Annual Report 2024" active c={c} />
            <CitationPill num={2} label="BSCS Filing Q3" c={c} />
            <CitationPill num={3} label="Risk Policy 2024" c={c} />
          </div>
        </VRow>
      </SectionRow>

      {/* Overlays */}
      <SectionRow title="Tooltip · Dropdown · Toast · Modal" c={c}>
        <VRow label="Tooltip" c={c}><Tooltip c={c} /></VRow>
        <VRow label="Dropdown Menu" c={c}><Dropdown c={c} /></VRow>
        <VRow label="Toast" c={c}>
          <VCell label="success" c={c}><Toast variant="success" c={c} /></VCell>
          <VCell label="error" c={c}><Toast variant="error" c={c} /></VCell>
          <VCell label="info" c={c}><Toast variant="info" c={c} /></VCell>
        </VRow>
        <VRow label="Modal" c={c}><Modal c={c} /></VRow>
      </SectionRow>

      {/* Skeleton & Empty State */}
      <SectionRow title="Skeleton & Empty State" c={c}>
        <VRow label="Skeleton" c={c}><Skeleton c={c} /></VRow>
        <VRow label="Empty State" c={c}><EmptyState c={c} /></VRow>
      </SectionRow>
    </div>
  );
}

// ── Root ──────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <div
      style={{
        fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
        background: "#D8DAD9",
        minHeight: "100vh",
        padding: 40,
        boxSizing: "border-box",
      }}
    >
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
        *{box-sizing:border-box;}
        p,h1,h2,h3,h4{margin:0;}
        textarea{resize:none;}
        button:focus-visible{outline:2px solid rgba(0,154,73,0.6);outline-offset:2px;}
      `}</style>

      {/* Page heading */}
      <div style={{ textAlign: "center", marginBottom: 40 }}>
        <p style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", color: "#6E7671", marginBottom: 6 }}>
          Habib Bank Limited · Internal
        </p>
        <h1 style={{ fontSize: 22, fontWeight: 600, color: "#0D0F0E", letterSpacing: "-0.01em" }}>
          HBL RAG Chatbot — Design System v1.0
        </h1>
        <p style={{ fontSize: 13, color: "#5C6360", marginTop: 4 }}>
          Component Library Sheet · Light Mode + Dark Mode · Inter · All variants
        </p>
      </div>

      {/* Mode label */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "#5C6360" }}>
          Light Mode
        </span>
      </div>
      <Sheet c={L} />

      {/* Dark divider */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "40px 0 16px" }}>
        <span style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "#5C6360" }}>
          Dark Mode
        </span>
      </div>
      <Sheet c={D} />

      <div style={{ textAlign: "center", marginTop: 48, paddingBottom: 8 }}>
        <p style={{ fontSize: 11, color: "#8A918D" }}>HBL RAG Chatbot · Design System v1.0 · Confidential</p>
      </div>
    </div>
  );
}
