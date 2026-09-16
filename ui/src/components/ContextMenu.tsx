import { useEffect, useLayoutEffect, useRef, useState } from "react";

export type MenuItem =
  | {
      label: string;
      onSelect: () => void;
      disabled?: boolean;
      /** Shown dimmed after the label, e.g. how many rows it applies to. */
      hint?: string;
      danger?: boolean;
    }
  | { separator: true };

interface Props {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}

/**
 * A right-click menu with actions for what was clicked.
 *
 * Replaces the webview's own menu ("Look Up", "Translate"), which offers text
 * tools for a word in the row rather than anything to do with the track.
 */
export function ContextMenu({ x, y, items, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: x, top: y });

  // Keep the menu on screen near the right and bottom edges.
  useLayoutEffect(() => {
    const menu = ref.current;
    if (!menu) return;
    const { width, height } = menu.getBoundingClientRect();
    setPosition({
      left: Math.max(4, Math.min(x, window.innerWidth - width - 4)),
      top: Math.max(4, Math.min(y, window.innerHeight - height - 4)),
    });
  }, [x, y]);

  useEffect(() => {
    const close = (event: Event) => {
      if (event instanceof MouseEvent && ref.current?.contains(event.target as Node)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="context-menu"
      role="menu"
      style={{ left: position.left, top: position.top }}
      onContextMenu={(event) => event.preventDefault()}
    >
      {items.map((item, index) =>
        "separator" in item ? (
          <div key={`sep-${index}`} className="context-separator" role="separator" />
        ) : (
          <button
            key={item.label}
            role="menuitem"
            className={item.danger ? "context-item danger" : "context-item"}
            disabled={item.disabled}
            onClick={() => {
              onClose();
              item.onSelect();
            }}
          >
            <span>{item.label}</span>
            {item.hint && <span className="context-hint">{item.hint}</span>}
          </button>
        ),
      )}
    </div>
  );
}
