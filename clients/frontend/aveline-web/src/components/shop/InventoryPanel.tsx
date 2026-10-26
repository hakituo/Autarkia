import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Gift, Package, RefreshCw, Utensils, X } from 'lucide-react';
import { shopApi, type InventoryEntry } from '../../api/extendedApi';
import { RecipientActionDialog } from './RecipientActionDialog';
import type { Recipient } from './shopTypes';

type InventoryTab = 'food' | 'gift';

const RECIPIENT_LABEL: Record<string, string> = { self: '共享', shared: '共享' };

export const InventoryPanel: React.FC<{
  open: boolean;
  recipients: Recipient[];
  onClose: () => void;
  onChanged: () => void;
}> = ({ open, recipients, onClose, onChanged }) => {
  const [tab, setTab] = useState<InventoryTab>('food');
  const [food, setFood] = useState<InventoryEntry[]>([]);
  const [gift, setGift] = useState<InventoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<{ entry: InventoryEntry; kind: InventoryTab } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [foodRes, giftRes] = await Promise.allSettled([
        shopApi.foodInventory(),
        shopApi.giftInventory(),
      ]);
      setFood(
        foodRes.status === 'fulfilled' && Array.isArray(foodRes.value?.data) ? foodRes.value.data : [],
      );
      setGift(
        giftRes.status === 'fulfilled' && Array.isArray(giftRes.value?.data) ? giftRes.value.data : [],
      );
      if (foodRes.status === 'rejected' && giftRes.status === 'rejected') {
        setError('加载库存失败');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  if (!open) return null;

  const list = tab === 'food' ? food : gift;

  const confirmAction = async (recipient: string) => {
    if (!action) return;
    setSubmitting(true);
    try {
      const res =
        action.kind === 'food'
          ? await shopApi.eat(action.entry.food_id || action.entry.item_id, { recipient, from_inventory: true })
          : await shopApi.useGift(action.entry.item_id, recipient);
      if (res?.success === false) {
        setNotice({ text: res.message || '操作失败', ok: false });
      } else {
        setNotice({ text: res?.message || '已使用', ok: true });
        setAction(null);
        await load();
        onChanged();
      }
    } catch (e: any) {
      setNotice({ text: e?.message || '操作失败', ok: false });
    } finally {
      setSubmitting(false);
      window.setTimeout(() => setNotice(null), 3000);
    }
  };

  return (
    <div className="fixed inset-0 z-[75] flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="w-full max-w-md h-full bg-zinc-950/95 border-l border-white/10 flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Package size={16} className="text-white/45" />
            <div>
              <h3 className="text-sm font-semibold text-white/90">库存</h3>
              <p className="text-[10px] text-white/30">已购食物与礼物</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => void load()}
              disabled={loading}
              className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/80 disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="p-1.5 rounded-full bg-white/5 text-white/40 hover:text-white/80">
              <X size={14} />
            </button>
          </div>
        </header>

        <div className="flex items-center gap-1 px-4 pt-3">
          {(
            [
              { id: 'food' as InventoryTab, label: '食物', icon: <Utensils size={12} />, count: food.length },
              { id: 'gift' as InventoryTab, label: '礼物', icon: <Gift size={12} />, count: gift.length },
            ]
          ).map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[11px] border ${
                tab === item.id
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                  : 'bg-white/5 text-white/40 border-transparent'
              }`}
            >
              {item.icon}
              {item.label}
              <span className="text-white/25">{item.count}</span>
            </button>
          ))}
        </div>

        {notice && (
          <div
            className={`mx-4 mt-2 flex items-center gap-1.5 rounded-xl px-3 py-2 text-[11px] ${
              notice.ok
                ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-200'
                : 'bg-rose-500/10 border border-rose-500/20 text-rose-200'
            }`}
          >
            {notice.text}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-4 space-y-2">
          {error ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              <AlertCircle size={30} className="text-rose-400/60" />
              <div className="text-xs text-white/50">{error}</div>
              <button onClick={() => void load()} className="text-[11px] text-emerald-300 hover:underline">
                重试
              </button>
            </div>
          ) : list.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-12 text-center">
              {tab === 'food' ? (
                <Utensils size={30} className="text-white/10" />
              ) : (
                <Gift size={30} className="text-white/10" />
              )}
              <div className="text-xs text-white/45">
                {tab === 'food' ? '还没有食物库存' : '还没有礼物库存'}
              </div>
              <div className="text-[10px] text-white/25">先去商城买一件吧</div>
            </div>
          ) : (
            list.map((entry, index) => {
              const key = `${entry.food_id || entry.item_id}-${entry.recipient}-${index}`;
              const name = entry.name || entry.item_name || entry.food_id || entry.item_id;
              const owner = RECIPIENT_LABEL[String(entry.recipient || '')] || entry.recipient || '共享';
              const expireAt = (entry as any).expire_at as number | undefined;
              return (
                <div
                  key={key}
                  className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5"
                >
                  <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center text-xl shrink-0">
                    {(entry as any).icon || (tab === 'food' ? '🍱' : '🎁')}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-white/85 truncate">{name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-white/30">
                      <span>归属 {owner}</span>
                      <span>x{entry.quantity}</span>
                      {expireAt ? (
                        <span>
                          到期 {new Date(expireAt * 1000).toLocaleDateString()}
                        </span>
                      ) : null}
                      {entry.effect_desc && <span className="truncate">{entry.effect_desc}</span>}
                    </div>
                  </div>
                  <button
                    onClick={() => setAction({ entry, kind: tab })}
                    className="shrink-0 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-[10px] text-white/55 hover:text-white/90"
                  >
                    {tab === 'food' ? '食用' : '使用'}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </aside>

      <RecipientActionDialog
        open={!!action}
        title={action?.kind === 'food' ? '食用库存食物' : '使用礼物'}
        itemName={action?.entry.name || action?.entry.item_name || ''}
        recipients={recipients}
        defaultRecipient="self"
        confirmText={action?.kind === 'food' ? '开吃' : '使用'}
        submitting={submitting}
        onClose={() => setAction(null)}
        onConfirm={(recipient) => void confirmAction(recipient)}
      />
    </div>
  );
};
