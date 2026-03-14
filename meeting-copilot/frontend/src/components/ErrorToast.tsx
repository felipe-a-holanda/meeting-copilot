import React, { useEffect } from 'react';

export interface Toast {
  id: string;
  message: string;
  type: 'error' | 'warning' | 'info';
}

interface ErrorToastProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

export function ErrorToast({ toasts, onDismiss }: ErrorToastProps) {
  useEffect(() => {
    if (toasts.length === 0) return;
    const latestId = toasts[toasts.length - 1].id;
    const timer = setTimeout(() => onDismiss(latestId), 5000);
    return () => clearTimeout(timer);
  }, [toasts, onDismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {toasts.map((toast) => {
        const bg =
          toast.type === 'error'
            ? 'bg-red-600'
            : toast.type === 'warning'
            ? 'bg-yellow-500'
            : 'bg-blue-600';
        return (
          <div
            key={toast.id}
            className={`${bg} text-white px-4 py-3 rounded-lg shadow-lg flex items-start gap-3`}
            role="alert"
          >
            <span className="flex-1 text-sm">{toast.message}</span>
            <button
              onClick={() => onDismiss(toast.id)}
              className="text-white/80 hover:text-white text-lg leading-none mt-0.5"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
