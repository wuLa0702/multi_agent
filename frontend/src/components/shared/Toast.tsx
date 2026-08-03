import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { X } from 'lucide-react';

export function showToast(message: string, type: 'success' | 'error' | 'info' = 'info') {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  root.render(<ToastMsg message={message} type={type} onDone={() => { root.unmount(); el.remove(); }} />);
}

function ToastMsg({ message, type, onDone }: { message: string; type: string; onDone: () => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    setVisible(true);
    const t1 = setTimeout(() => setVisible(false), 2500);
    const t2 = setTimeout(onDone, 2800);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, []);

  const colors: Record<string, string> = {
    success: 'bg-green-600',
    error: 'bg-red-600',
    info: 'bg-neutral-800 dark:bg-neutral-700',
  };

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 flex items-center gap-2 px-3 py-2 rounded-lg text-white text-xs shadow-lg transition-all duration-300 ${
        colors[type] || colors.info
      } ${visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2'}`}
    >
      <span>{message}</span>
      <button onClick={onDone} className="opacity-60 hover:opacity-100">
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
