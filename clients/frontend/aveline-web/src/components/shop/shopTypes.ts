import {
  BookOpen,
  Cpu,
  Gem,
  Gift,
  LayoutGrid,
  Shirt,
  ToyBrick,
  Utensils,
} from 'lucide-react';
import type { ShopItem } from '../../api/extendedApi';

export const SHOP_CATEGORIES = [
  { id: 'all', label: '全部', icon: LayoutGrid },
  { id: 'food', label: '食物', icon: Utensils },
  { id: 'gift', label: '礼物', icon: Gift },
  { id: 'toy', label: '玩具', icon: ToyBrick },
  { id: 'book', label: '书籍', icon: BookOpen },
  { id: 'clothing', label: '服饰', icon: Shirt },
  { id: 'tech', label: '科技', icon: Cpu },
  { id: 'luxury', label: '奢侈品', icon: Gem },
] as const;

export type ShopCategoryId = (typeof SHOP_CATEGORIES)[number]['id'];

export const CATEGORY_LABEL: Record<string, string> = {
  food: '食物',
  gift: '礼物',
  toy: '玩具',
  book: '书籍',
  clothing: '服饰',
  tech: '科技',
  luxury: '奢侈品',
};

export interface Recipient {
  id: string;
  name: string;
}

/** 共享钱包在商品卡上的展示口径（后端为无限金币）。 */
export interface WalletInfo {
  coins: number;
  unlimited: boolean;
}

export const DEFAULT_RECIPIENT: Recipient = { id: 'self', name: '共享' };

export function isFood(item: ShopItem): boolean {
  return item.category === 'food' || Boolean(item.nutrition);
}

export function foodEffectTags(item: ShopItem): Array<{ label: string; tone: string }> {
  const nutrition = item.nutrition;
  if (!nutrition) return [];
  const tags: Array<{ label: string; tone: string }> = [];
  if (nutrition.hunger) tags.push({ label: `饥饿 -${nutrition.hunger}`, tone: 'text-orange-200 bg-orange-500/15' });
  if (nutrition.thirst) tags.push({ label: `口渴 -${nutrition.thirst}`, tone: 'text-sky-200 bg-sky-500/15' });
  if (nutrition.energy) tags.push({ label: `精力 +${nutrition.energy}`, tone: 'text-amber-200 bg-amber-500/15' });
  if (nutrition.health) tags.push({ label: `健康 +${nutrition.health}`, tone: 'text-emerald-200 bg-emerald-500/15' });
  return tags;
}
