import React from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { cn } from '@/utils/cn';

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

export function Dialog({ open, onClose, title, description, children, className }: DialogProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm animate-fade-in" />
        <DialogPrimitive.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 animate-slide-up w-full max-w-md',
            'rounded-xl border border-[#1e293b] bg-[#111827] p-6 shadow-2xl focus:outline-none',
            className
          )}
        >
          <div className="flex items-start justify-between gap-4 mb-4">
            <div>
              {title && (
                <DialogPrimitive.Title className="text-base font-semibold text-[#f8fafc]">
                  {title}
                </DialogPrimitive.Title>
              )}
              {description && (
                <DialogPrimitive.Description className="mt-1 text-sm text-[#94a3b8]">
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>
            <DialogPrimitive.Close
              onClick={onClose}
              className="rounded-md p-1 text-[#64748b] hover:text-[#f8fafc] hover:bg-[#131a29] transition-colors focus:outline-none focus:ring-2 focus:ring-[#3b82f6]"
              aria-label="Close dialog"
            >
              <X size={16} />
            </DialogPrimitive.Close>
          </div>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
