"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type ToastVariant = "info" | "success" | "error";

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastApi {
  show: (message: string, variant?: ToastVariant) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

/** Access the toast API. Must be used within <ToastProvider>. */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within <ToastProvider>");
  }
  return ctx;
}

let nextId = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (message: string, variant: ToastVariant = "info") => {
      const id = ++nextId;
      setToasts((prev) => [...prev, { id, message, variant }]);
      window.setTimeout(() => remove(id), 4500);
    },
    [remove]
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (m: string) => show(m, "success"),
      error: (m: string) => show(m, "error"),
      info: (m: string) => show(m, "info"),
    }),
    [show]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2"
        role="region"
        aria-live="polite"
        aria-label="Notifications"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={
              "pointer-events-auto flex max-w-sm items-start gap-3 rounded-md border px-4 py-3 text-sm shadow-lg " +
              (t.variant === "error"
                ? "border-red-200 bg-red-50 text-red-800"
                : t.variant === "success"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : "border-[color:var(--color-divider,#E8E8E8)] bg-white text-[color:var(--color-inkwell,#000)]")
            }
          >
            <span className="flex-1">{t.message}</span>
            <button
              type="button"
              onClick={() => remove(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 opacity-60 transition hover:opacity-100"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
