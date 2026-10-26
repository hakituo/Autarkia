import React from 'react';
import { ShoppingBag, Utensils } from 'lucide-react';
import type { ShopItem } from '../../api/extendedApi';
import { CATEGORY_LABEL, foodEffectTags, isFood } from './shopTypes';

export const ShopItemCard: React.FC<{
  item: ShopItem;
  layout: 'grid' | 'list';
  busy?: boolean;
  onBuy: () => void;
  onEat: () => void;
}> = ({ item, layout, busy, onBuy, onEat }) => {
  const food = isFood(item);
  const tags = foodEffectTags(item);

  if (layout === 'list') {
    return (
      <div className="glass-card rounded-2xl p-3.5 border border-white/10 flex items-start gap-3">
        <div className="shrink-0 w-14 h-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-3xl">
          {item.icon || '📦'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-base font-semibold text-white/90 truncate">{item.name}</div>
              <div className="mt-0.5 text-xs text-white/40 line-clamp-2">{item.description}</div>
            </div>
            <div className="shrink-0 text-right">
              <div className="px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-200 border border-amber-500/20 text-xs font-mono">
                {item.price}
              </div>
              <div className="mt-1 text-[10px] text-white/25">{CATEGORY_LABEL[item.category] || item.category}</div>
            </div>
          </div>
          {tags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {tags.map((tag) => (
                <span key={tag.label} className={`px-1.5 py-0.5 rounded-full text-[10px] ${tag.tone}`}>
                  {tag.label}
                </span>
              ))}
            </div>
          )}
          <div className="mt-2.5 flex items-center gap-2">
            <button
              disabled={busy}
              onClick={onBuy}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200 disabled:opacity-40"
            >
              <ShoppingBag size={11} />
              购买
            </button>
            {food && (
              <button
                disabled={busy}
                onClick={onEat}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-[11px] text-white/60 disabled:opacity-40"
              >
                <Utensils size={11} />
                食用
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative flex flex-col rounded-2xl bg-white/5 border border-white/5 hover:border-white/15 hover:bg-white/10 transition-all p-4">
      <div className="text-5xl mb-3 text-center group-hover:scale-105 transition-transform duration-200">
        {item.icon || '📦'}
      </div>
      <div className="text-sm font-semibold text-white/90 text-center truncate">{item.name}</div>
      <div className="mt-1 text-[11px] text-white/40 text-center line-clamp-2 min-h-[28px]">
        {item.description}
      </div>
      {tags.length > 0 && (
        <div className="mt-2 flex flex-wrap justify-center gap-1">
          {tags.slice(0, 3).map((tag) => (
            <span key={tag.label} className={`px-1.5 py-0.5 rounded-full text-[9px] ${tag.tone}`}>
              {tag.label}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 flex items-center justify-center gap-1 text-[10px] text-white/25">
        <span className="px-1.5 py-0.5 rounded bg-white/5">
          {CATEGORY_LABEL[item.category] || item.category}
        </span>
        <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-200/80 font-mono">{item.price}</span>
      </div>
      <div className="mt-3 flex items-center gap-1.5">
        <button
          disabled={busy}
          onClick={onBuy}
          className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/25 text-[11px] text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
        >
          <ShoppingBag size={11} />
          购买
        </button>
        {food && (
          <button
            disabled={busy}
            onClick={onEat}
            className="px-2.5 py-1.5 rounded-lg bg-white/5 border border-white/10 text-white/55 hover:text-white/90 disabled:opacity-40"
            title="直接食用"
          >
            <Utensils size={12} />
          </button>
        )}
      </div>
    </div>
  );
};
