import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
}

/**
 * A draggable panel that floats over the main window.
 *
 * Unlike a modal it does not block the view behind it, which matters here: the
 * sync overview is something you glance at while working in the track list, not
 * a dialog you must dismiss.
 */
export function FloatingWindow({ title, onClose, children, width = 900 }: Props) {
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const drag = useRef<{ dx: number; dy: number } | null>(null);
  const frame = useRef<HTMLDivElement | null>(null);

  const onPointerDown = (event: React.PointerEvent) => {
    const box = frame.current?.getBoundingClientRect();
    if (!box) return;
    drag.current = { dx: event.clientX - box.left, dy: event.clientY - box.top };
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  };

  const onPointerMove = useCallback((event: PointerEvent) => {
    if (!drag.current) return;
    const box = frame.current?.getBoundingClientRect();
    const w = box?.width ?? 0;
    // Keep a strip of the window on screen so it can always be grabbed again.
    const x = Math.min(Math.max(event.clientX - drag.current.dx, 8 - w + 120), window.innerWidth - 120);
    const y = Math.min(Math.max(event.clientY - drag.current.dy, 0), window.innerHeight - 44);
    setPosition({ x, y });
  }, []);

  const stopDrag = useCallback(() => {
    drag.current = null;
  }, []);

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopDrag);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDrag);
    };
  }, [onPointerMove, stopDrag]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const style: React.CSSProperties = position
    ? { left: position.x, top: position.y, width, transform: "none" }
    : { width };

  return (
    <div ref={frame} className="floating" style={style}>
      <header className="floating-bar" onPointerDown={onPointerDown}>
        <span className="floating-title">{title}</span>
        <button className="chip" onPointerDown={(e) => e.stopPropagation()} onClick={onClose}>
          close
        </button>
      </header>
      <div className="floating-body">{children}</div>
    </div>
  );
}
