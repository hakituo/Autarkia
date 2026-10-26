/** 生活模块（对齐安卓 LifeScreen）共用的数据类型。 */
import type { HealthSnapshot, NutritionEntryRaw, WaterEntryRaw } from '../../api/extendedApi';

export type LifeTab = 'health' | 'schedule' | 'water' | 'meal';

export interface StudySessionLite {
  topic?: string;
  content?: string;
  time?: string;
}

export interface MealLite {
  type?: string;
  content?: string;
  time?: string;
}

export interface LifePortrait {
  schedule?: { wakeup?: string | null; sleep?: string | null };
  drink?: { total_ml?: number; count?: number };
  study?: { total_minutes?: number; count?: number; sessions?: StudySessionLite[] };
  meals?: MealLite[];
  body_metrics?: { weight_kg?: number | null; weight_updated_at?: number };
  mode?: {
    preference_mode?: string;
    reduced_mode_active?: boolean;
    reduced_mode_reason?: string;
    reduced_mode_expected_end_ts?: number;
  };
}

export interface LifeNutrition {
  date?: string;
  nutrition_entries: NutritionEntryRaw[];
  water_intake_entries: WaterEntryRaw[];
}

export interface LifeData {
  health: HealthSnapshot | null;
  portrait: LifePortrait | null;
  nutrition: LifeNutrition;
}

export const EMPTY_NUTRITION: LifeNutrition = {
  nutrition_entries: [],
  water_intake_entries: [],
};

/** 生成 YYYY-MM-DD（本地时区，不受 UTC 偏移影响）。 */
export function todayStr(date = new Date()): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** ISO 时间戳 / "HH:mm" 统一成 HH:mm 展示。 */
export function formatClock(value?: string | null): string {
  if (!value) return '--';
  const raw = String(value).trim();
  const match = raw.match(/(\d{2}):(\d{2})/);
  if (match) return `${match[1]}:${match[2]}`;
  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) {
    return `${String(parsed.getHours()).padStart(2, '0')}:${String(parsed.getMinutes()).padStart(2, '0')}`;
  }
  return raw;
}

/** 分钟 → "Xh Ym"。 */
export function formatMinutes(minutes?: number | null): string {
  if (minutes == null || !Number.isFinite(minutes) || minutes <= 0) return '--';
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h <= 0) return `${m} 分钟`;
  if (m === 0) return `${h} 小时`;
  return `${h} 小时 ${m} 分`;
}

/** 0-1 的体脂率等比例转百分比文本。 */
export function formatPercent(value?: number | null, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '--';
  const pct = value <= 1 ? value * 100 : value;
  return `${pct.toFixed(digits)}%`;
}

export function formatNumber(value?: number | null, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return Number(value).toFixed(digits);
}
