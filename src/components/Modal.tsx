import React, { useEffect } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  blockBackdropClose?: boolean;
  maxWidthClass?: string;
  children: React.ReactNode;
}

export const Modal: React.FC<ModalProps> = ({
  open,
  title,
  onClose,
  blockBackdropClose = false,
  maxWidthClass = 'max-w-2xl',
  children,
}) => {
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !blockBackdropClose) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, blockBackdropClose, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 p-3 sm:p-4 overflow-y-auto"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !blockBackdropClose) {
          onClose();
        }
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`w-full ${maxWidthClass} rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] text-[var(--hb-text)] shadow-xl max-h-[92vh] flex flex-col`}
      >
        <div className="flex items-center justify-between gap-4 border-b border-[var(--hb-border)] px-5 py-3.5 shrink-0">
          <h2 className="text-base font-bold text-[var(--hb-text)] truncate">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="بستن پنجره"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-[var(--hb-muted)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-5 flex-1">{children}</div>
      </div>
    </div>
  );
};
