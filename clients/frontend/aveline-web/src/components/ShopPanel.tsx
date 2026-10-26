import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, CheckCircle2, Coins, Package, RefreshCw, Search, Sparkles } from 'lucide-react';
import { api } from '../api/apiService';
import { shopApi, type ShopItem } from '../api/extendedApi';
import { useAvelineStore } from '../store/useStore';
import { ShopItemCard } from './shop/ShopItemCard';
import { InventoryPanel } from './shop/InventoryPanel';
import { RecipientActionDialog } from './shop/RecipientActionDialog';
import { DEFAULT_RECIPIENT, SHOP_CATEGORIES, type Recipient, type ShopCategoryId } from './shop/shopTypes';

const PAGE_SIZE = 24;

type DialogState =
  | { kind: 'buy'; item: ShopItem }
  | { kind: 'eat'; item: ShopItem }
  | null;

/**
 * 商城（对齐安卓 FoodScreen）：
 * 8 类目浏览 + 分页加载 + 购买（选对象/数量）+ 直接食用 + 库存（食物/礼物）。
 */
const ShopPanel: React.FC<{ platform?: 'web' | 'mobile' }> = ({ platform = 'web' }) => {
  const [category, setCategory] = useState<ShopCategoryId>('all');
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<ShopItem[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wallet, setWallet] = useState<{ coins: number; unlimited: boolean }>({ coins: 0, unlimited: true });
  const [recipients, setRecipients] = useState<Recipient[]>([DEFAULT_RECIPIENT]);
  const [dialog, setDialog] = useState<DialogState>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const messageTimer = useRef<number | null>(null);

  const { lifeStatus } = useAvelineStore();
  const layout = platform === 'mobile' ? 'list' : 'grid';

  const showMessage = useCallback((text: string, type: 'success' | 'error') => {
    setMessage({ text, type });
    if (messageTimer.current) window.clearTimeout(messageTimer.current);
    messageTimer.current = window.setTimeout(() => setMessage(null), 3000);
  }, []);

  const loadPage = useCallback(
    async (targetPage: number, replace: boolean) => {
      if (replace) {
        setLoading(true);
        setError(null);
      } else {
        setLoadingMore(true);
      }
      try {
        const res = await shopApi.menu({
          category: category === 'all' ? undefined : category,
          page: targetPage,
          page_size: PAGE_SIZE,
        });
        const incoming: ShopItem[] = Array.isArray(res?.items) ? res.items : [];
        setItems((prev) => (replace ? incoming : [...prev, ...incoming]));
        setHasMore(Boolean(res?.has_more));
        setPage(targetPage);
        if (typeof res?.coins === 'number') {
          setWallet({ coins: res.coins, unlimited: Boolean(res.unlimited_coins) });
        }
      } catch (e: any) {
        setError(e?.message || '加载商城失败');
        if (replace) setItems([]);
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [category],
  );

  useEffect(() => {
    void loadPage(1, true);
  }, [loadPage]);

  useEffect(() => {
    api
      .listPersonas()
      .then((res: any) => {
        const raw = Array.isArray(res) ? res : Array.isArray(res?.data) ? res.data : [];
        const mapped: Recipient[] = raw
          .map((item: any) => {
            const id = String(item?.role_id || item?.filename || item?.role || '').trim();
            const name = String(item?.name || item?.role || item?.filename || id).trim();
            return id ? { id, name } : null;
          })
          .filter(Boolean) as Recipient[];
        setRecipients([DEFAULT_RECIPIENT, ...mapped]);
      })
      .catch(() => setRecipients([DEFAULT_RECIPIENT]));
  }, []);

  useEffect(() => {
    return () => {
      if (messageTimer.current) window.clearTimeout(messageTimer.current);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(q));
  }, [items, query]);

  const handleBuy = async (recipient: string, quantity: number) => {
    if (!dialog) return;
    setSubmitting(true);
    try {
      const res = await shopApi.buy(dialog.item.id, quantity, recipient);
      if (res?.success === false) {
        showMessage(res?.message || '购买失败', 'error');
      } else {
        showMessage(res?.message || '购买成功', 'success');
        setDialog(null);
      }
    } catch (e: any) {
      showMessage(e?.message || '购买失败', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const handleEat = async (recipient: string) => {
    if (!dialog) return;
    setSubmitting(true);
    try {
      const res = await shopApi.eat(dialog.item.id, { recipient, from_inventory: true });
      if (res?.success === false) {
        showMessage(res?.message || '食用失败', 'error');
      } else {
        showMessage(res?.message || '已食用', 'success');
        setDialog(null);
      }
    } catch (e: any) {
      showMessage(e?.message || '食用失败', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const coins = wallet.unlimited ? lifeStatus?.coins ?? wallet.coins : wallet.coins;

  return (
    <div className={`flex-1 h-full overflow-y-auto custom-scrollbar ${platform === 'mobile' ? 'p-3' : 'p-4 md:p-8'}`}>
      <div className="max-w-7xl mx-auto space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
              <Package className="text-white/70" size={18} />
            </div>
            <div>
              <h2 className="text-lg md:text-xl font-semibold text-white/95 tracking-wide">Mall</h2>
              <div className="flex items-center gap-2 mt-0.5 text-[10px] text-white/40">
                <span className="flex items-center gap-1">
                  <Coins size={10} className="text-yellow-300" />
                  <span className="font-mono text-yellow-200/90">{wallet.unlimited ? '无限' : coins}</span>
                </span>
                <span className="w-px h-3 bg-white/10" />
                <span className="flex items-center gap-1">
                  <Sparkles size={10} className="text-emerald-300" />
                  LV.{lifeStatus?.level || 1}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden md:flex items-center gap-2 rounded-xl bg-white/5 border border-white/10 px-3 py-1.5">
              <Search size={13} className="text-white/35" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索商品…"
                className="bg-transparent outline-none text-xs text-white/80 placeholder:text-white/25 w-36"
              />
            </div>
            <button
              onClick={() => void loadPage(1, true)}
              disabled={loading}
              className="p-2 rounded-xl bg-white/5 border border-white/10 text-white/45 hover:text-white/85 disabled:opacity-40"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={() => setInventoryOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 border border-white/10 text-[11px] text-white/60 hover:text-white/90"
            >
              <Package size={12} />
              库存
            </button>
          </div>
        </div>

        <div className="md:hidden flex items-center gap-2 rounded-xl bg-white/5 border border-white/10 px-3 py-1.5">
          <Search size={13} className="text-white/35" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索商品…"
            className="bg-transparent outline-none text-xs text-white/80 placeholder:text-white/25 w-full"
          />
        </div>

        <div className="flex overflow-x-auto no-scrollbar gap-2 pb-1">
          {SHOP_CATEGORIES.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setCategory(cat.id)}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs whitespace-nowrap border transition-all ${
                category === cat.id
                  ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25'
                  : 'bg-white/5 text-white/45 border-transparent hover:text-white/80 hover:bg-white/10'
              }`}
            >
              <cat.icon size={13} />
              {cat.label}
            </button>
          ))}
        </div>

        <AnimatePresence>
          {message && (
            <motion.div
              initial={{ opacity: 0, y: -12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              className={`fixed top-[calc(env(safe-area-inset-top)+16px)] left-1/2 -translate-x-1/2 z-[90] flex items-center gap-2 px-5 py-2.5 rounded-full border backdrop-blur-sm text-xs font-medium ${
                message.type === 'success'
                  ? 'bg-emerald-500/15 border-emerald-500/40 text-emerald-200'
                  : 'bg-rose-500/15 border-rose-500/40 text-rose-200'
              }`}
            >
              {message.type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
              {message.text}
            </motion.div>
          )}
        </AnimatePresence>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <div className="w-10 h-10 border-4 border-emerald-500/20 border-t-emerald-500 rounded-full animate-spin" />
            <div className="text-xs text-white/40">加载商城…</div>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 rounded-3xl bg-rose-500/5 border border-rose-500/10">
            <AlertCircle size={40} className="text-rose-400" />
            <div className="text-sm text-rose-200">{error}</div>
            <button
              onClick={() => void loadPage(1, true)}
              className="px-5 py-2 rounded-xl bg-rose-500/15 text-rose-200 text-xs border border-rose-500/20"
            >
              重试
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-2 rounded-3xl bg-white/5 border border-white/10">
            <Package size={38} className="text-white/10" />
            <div className="text-sm text-white/45">没有找到商品</div>
          </div>
        ) : (
          <>
            <div
              className={
                layout === 'grid'
                  ? 'grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 md:gap-4'
                  : 'space-y-2.5'
              }
            >
              {filtered.map((item) => (
                <ShopItemCard
                  key={item.id}
                  item={item}
                  layout={layout}
                  busy={submitting}
                  onBuy={() => setDialog({ kind: 'buy', item })}
                  onEat={() => setDialog({ kind: 'eat', item })}
                />
              ))}
            </div>

            {hasMore && !query && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={() => void loadPage(page + 1, false)}
                  disabled={loadingMore}
                  className="px-5 py-2 rounded-full bg-white/5 border border-white/10 text-xs text-white/55 hover:text-white/85 disabled:opacity-40"
                >
                  {loadingMore ? '加载中…' : '加载更多'}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <RecipientActionDialog
        open={dialog?.kind === 'buy'}
        title="购买商品"
        itemName={dialog?.item.name || ''}
        price={dialog?.item.price}
        recipients={recipients}
        defaultRecipient="self"
        showQuantity
        confirmText="确认购买"
        submitting={submitting}
        onClose={() => setDialog(null)}
        onConfirm={(recipient, quantity) => void handleBuy(recipient, quantity)}
      />

      <RecipientActionDialog
        open={dialog?.kind === 'eat'}
        title="食用"
        subtitle="选择谁吃"
        itemName={dialog?.item.name || ''}
        recipients={recipients}
        defaultRecipient="self"
        confirmText="开吃"
        submitting={submitting}
        onClose={() => setDialog(null)}
        onConfirm={(recipient) => void handleEat(recipient)}
      />

      <InventoryPanel
        open={inventoryOpen}
        recipients={recipients}
        onClose={() => setInventoryOpen(false)}
        onChanged={() => showMessage('库存已更新', 'success')}
      />
    </div>
  );
};

export default ShopPanel;
