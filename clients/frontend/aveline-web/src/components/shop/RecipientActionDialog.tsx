import React, { useEffect, useState } from 'react';
import { Minus, Plus, X } from 'lucide-react';
import type { Recipient } from './shopTypes';

/**
 * 购买 / 食用 / 使用礼物共用的「选对象」弹窗。
 * 安卓端是 AlertDialog + 单选，这里保持同样的两步式确认。
 */
export const RecipientActionDialog: React.FC<{
  open: boolean;
  title: string;
  subtitle?: string;
  itemName: string;
  price?: number;
  recipients: Recipient[];
  defaultRecipient: string;
  showQuantity?: boolean;
  confirmText: string;
  submitting?: boolean;
  onClose: () => void;
  onConfirm: (recipient: string, quantity: number) => void;
}> = ({
  open,
  title,
  subtitle,
  itemName,
  price,
  recipients,
  defaultRecipient,
  showQuantity,
  confirmText,
  submitting,
  onClose,
  onConfirm,
}) => {
  const [recipient, setRecipient] = useState(defaultRecipient);
  const [quantity, setQuantity] = useState(1);

  useEffect(() => {
    if (!open) return;
    setRecipient(defaultRecipient);
    setQuantity(1);
  }, [open, defaultRecipient]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-zinc-950/95 shadow-2xl">
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-white/5">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-white/90 truncate">{title}</h3>
            <p className="text-[11px] text-white/35 mt-0.5 truncate">{subtitle || itemName}</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/70">
            <X size={14} />
          </button>
        </header>

        <div className="p-5 space-y-4">
          <div className="rounded-xl bg-white/5 border border-white/10 px-3 py-2.5">
            <div className="text-xs text-white/45">商品</div>
            <div className="text-sm text-white/85 mt-0.5 truncate">{itemName}</div>
            {price != null && (
              <div className="text-[11px] text-amber-200/80 mt-1 font-mono">单价 {price}</div>
            )}
          </div>

          <div>
            <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1.5">给谁</div>
            <div className="flex flex-wrap gap-1.5">
              {recipients.map((item) => (
                <button
                  key={item.id}
                  onClick={() => setRecipient(item.id)}
                  className={`px-3 py-1.5 rounded-full text-[11px] border transition-colors ${
                    recipient === item.id
                      ? 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
                      : 'bg-white/5 text-white/45 border-white/10 hover:text-white/80'
                  }`}
                >
                  {item.name}
                </button>
              ))}
            </div>
          </div>

          {showQuantity && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-white/30 mb-1.5">数量</div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                  className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 text-white/60 flex items-center justify-center"
                >
                  <Minus size={12} />
                </button>
                <span className="w-10 text-center text-sm text-white/85 tabular-nums">{quantity}</span>
                <button
                  onClick={() => setQuantity((q) => Math.min(99, q + 1))}
                  className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 text-white/60 flex items-center justify-center"
                >
                  <Plus size={12} />
                </button>
                {price != null && (
                  <span className="ml-auto text-[11px] text-white/35 font-mono">
                    合计 {price * quantity}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-white/5">
          <button onClick={onClose} className="px-4 py-2 text-xs text-white/45 hover:text-white/80">
            取消
          </button>
          <button
            disabled={submitting}
            onClick={() => onConfirm(recipient, quantity)}
            className="px-4 py-2 rounded-xl bg-emerald-500/15 border border-emerald-500/25 text-xs text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
          >
            {submitting ? '处理中…' : confirmText}
          </button>
        </footer>
      </div>
    </div>
  );
};
