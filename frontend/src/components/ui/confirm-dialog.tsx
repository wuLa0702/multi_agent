import { useState, useEffect, useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import { AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ConfirmDialogProps {
  message: string;
  title?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'default' | 'destructive';
  onResult: (confirmed: boolean) => void;
}

function ConfirmDialog({
  message,
  title = '确认操作',
  confirmLabel = '确定',
  cancelLabel = '取消',
  variant = 'default',
  onResult,
}: ConfirmDialogProps) {
  const [visible, setVisible] = useState(false);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    // Trigger enter animation on next frame
    requestAnimationFrame(() => setVisible(true));
  }, []);

  const handleResult = useCallback(
    (confirmed: boolean) => {
      setClosing(true);
      // Wait for exit animation before resolving
      setTimeout(() => onResult(confirmed), 200);
    },
    [onResult],
  );

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !closing) handleResult(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [closing, handleResult]);

  return (
    <div
      className={`fixed inset-0 z-[100] flex items-center justify-center transition-all duration-200 ${
        visible && !closing ? 'opacity-100' : 'opacity-0'
      }`}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={() => handleResult(false)}
      />

      {/* Dialog */}
      <div
        className={`relative bg-background border border-border rounded-xl shadow-2xl max-w-sm w-full mx-4 p-6 transition-all duration-200 ${
          visible && !closing
            ? 'scale-100 translate-y-0'
            : 'scale-95 translate-y-2'
        }`}
      >
        <div className="flex items-start gap-3">
          <div
            className={`shrink-0 mt-0.5 rounded-full p-2 ${
              variant === 'destructive'
                ? 'bg-destructive/10 text-destructive'
                : 'bg-primary/10 text-primary'
            }`}
          >
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground mt-1.5 leading-relaxed">
              {message}
            </p>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleResult(false)}
            autoFocus
          >
            {cancelLabel}
          </Button>
          <Button
            variant={variant === 'destructive' ? 'destructive' : 'default'}
            size="sm"
            onClick={() => handleResult(true)}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Promise-based confirm dialog — replaces window.confirm()
 *
 * Usage:
 *   const ok = await showConfirm('确定删除吗？');
 *   if (ok) { doDelete(); }
 */
export function showConfirm(
  message: string,
  options?: {
    title?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    variant?: 'default' | 'destructive';
  },
): Promise<boolean> {
  return new Promise(resolve => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    const root = createRoot(el);

    const cleanup = (result: boolean) => {
      root.unmount();
      el.remove();
      resolve(result);
    };

    root.render(
      <ConfirmDialog
        message={message}
        title={options?.title}
        confirmLabel={options?.confirmLabel}
        cancelLabel={options?.cancelLabel}
        variant={options?.variant}
        onResult={cleanup}
      />,
    );
  });
}
