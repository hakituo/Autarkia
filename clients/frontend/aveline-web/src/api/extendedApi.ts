/**
 * 扩展接口层：对齐安卓端已接入、网页端此前缺失的业务域。
 *
 * 只做「路径 + 类型」的薄封装，复用 apiService 的 get/post/delete，
 * 不放任何 UI 逻辑，避免 apiService.ts 继续膨胀。
 */
import api from './apiService';

const NO_RETRY = { retries: 0 };

/* ============================== 健康 / 生活 ============================== */

export interface NutritionEntryRaw {
  title?: string | null;
  meal_type?: string | null;
  calories?: number | null;
  protein?: number | null;
  carbs?: number | null;
  fat?: number | null;
  time?: string | null;
  saturated_fat?: number | null;
  trans_fat?: number | null;
  dietary_fiber?: number | null;
  sugar?: number | null;
  cholesterol?: number | null;
  sodium?: number | null;
  potassium?: number | null;
  vitamin_a?: number | null;
  vitamin_c?: number | null;
  calcium?: number | null;
  iron?: number | null;
  source?: string | null;
}

export interface WaterEntryRaw {
  amount_ml?: number | null;
  time?: string | null;
}

/** /api/v1/context/health/sync/latest 的 data 字段（穿戴设备最新快照）。 */
export interface HealthSnapshot {
  steps?: number;
  steps_today?: number;
  heart_rate?: number;
  heart_rate_timestamp?: string;
  weight_kg?: number;
  height_m?: number;
  body_fat_percent?: number;
  skeletal_muscle_percent?: number;
  basal_metabolic_rate?: number;
  muscle_mass?: number;
  body_fat_mass?: number;
  fat_free_mass?: number;
  skeletal_muscle_mass?: number;
  total_body_water?: number;
  sleep_minutes?: number;
  sleep_start_time?: string;
  sleep_end_time?: string;
  sleep_stage_awake_minutes?: number;
  sleep_stage_light_minutes?: number;
  sleep_stage_deep_minutes?: number;
  sleep_stage_rem_minutes?: number;
  sleep_score?: number;
  blood_pressure_systolic?: number;
  blood_pressure_diastolic?: number;
  body_temperature?: number;
  blood_glucose?: number;
  skin_temperature?: number;
  blood_oxygen?: number;
  floors_climbed?: number;
  water_intake_ml?: number;
  water_intake_goal_ml?: number;
  nutrition_calories?: number;
  nutrition_goal_calories?: number;
  nutrition_protein?: number;
  nutrition_carbs?: number;
  nutrition_fat?: number;
  nutrition_dietary_fiber?: number;
  nutrition_sugar?: number;
  nutrition_sodium?: number;
  nutrition_potassium?: number;
  nutrition_saturated_fat?: number;
  nutrition_trans_fat?: number;
  nutrition_cholesterol?: number;
  nutrition_vitamin_a?: number;
  nutrition_vitamin_c?: number;
  nutrition_calcium?: number;
  nutrition_iron?: number;
  energy_score?: number;
  active_calories_burned?: number;
  total_calories_burned?: number;
  active_time_minutes?: number;
  total_distance_km?: number;
  steps_goal?: number;
  active_calories_goal?: number;
  active_time_goal_minutes?: number;
  sleep_apnea_sign?: string;
  irregular_heart_rhythm?: string;
  nutrition_entries?: NutritionEntryRaw[];
  water_intake_entries?: WaterEntryRaw[];
  collected_at?: string;
  source?: string;
}

export const healthApi = {
  /** 最新健康快照；无数据时后端返回 error_response，调用方按失败处理。 */
  latest: () => api.get('/api/v1/context/health/sync/latest', undefined, { ...NO_RETRY, silent: true }),
  /** 某日逐条饮食 + 饮水明细。 */
  nutrition: (date?: string) =>
    api.get('/api/v1/context/health/nutrition', date ? { date } : undefined, NO_RETRY),
};

export const dailyApi = {
  portraitToday: () => api.get('/api/v1/context/daily/portrait/today', undefined, NO_RETRY),
  recordDrink: (payload: { units?: number; amount_ml?: number; beverage?: string }) =>
    api.post('/api/v1/context/daily/record/drink', payload, NO_RETRY),
  recordSchedule: (payload: { sleep?: string; wakeup?: string; date?: string }) =>
    api.post('/api/v1/context/daily/record/schedule', payload, NO_RETRY),
};

/* ============================== 数字健康 ============================== */

export interface AppLimit {
  package_name: string;
  app_name: string;
  limit_ms: number;
  usage_today_ms: number;
  ratio: number;
  session_limit_ms: number;
  session_gap_ms: number;
  cooldown_ms: number;
  source?: string;
}

export const wellbeingApi = {
  limits: (targetDate?: string) =>
    api.get(
      '/api/v1/context/wellbeing/app-limits',
      targetDate ? { target_date: targetDate } : undefined,
      NO_RETRY,
    ),
  setLimit: (payload: {
    package_name: string;
    app_name?: string;
    limit_ms: number;
    session_limit_ms?: number;
    session_gap_ms?: number;
    cooldown_ms?: number;
    target_date?: string;
  }) => api.post('/api/v1/context/wellbeing/app-limit', payload, NO_RETRY),
  removeLimit: (packageName: string, targetDate?: string) =>
    api.delete(
      `/api/v1/context/wellbeing/app-limit/${encodeURIComponent(packageName)}${
        targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : ''
      }`,
      NO_RETRY,
    ),
};

/* ============================== 学习计划 ============================== */

export interface PlanItem {
  id: string;
  time?: string | null;
  title: string;
  description?: string | null;
  category?: string;
  subject?: string | null;
  priority?: string;
  estimated_duration_minutes?: number;
  actual_minutes?: number;
  status?: string;
}

export interface DailyPlan {
  date: string;
  daily_goal_minutes?: number;
  items: PlanItem[];
  notes?: string | null;
  source?: string;
  updated_at?: number;
}

export const studyPlanApi = {
  get: (date: string) => api.get('/api/v1/study-daily/plan', { date }, NO_RETRY),
  setItemStatus: (payload: { date: string; item_id: string; done: boolean }) =>
    api.post('/api/v1/study-daily/plan/item/status', payload, NO_RETRY),
  addItem: (payload: { date: string; time?: string; title: string; duration_minutes?: number }) =>
    api.post('/api/v1/study-daily/plan/item/add', payload, NO_RETRY),
  updateItem: (payload: {
    date: string;
    item_id: string;
    time?: string;
    title: string;
    duration_minutes?: number;
  }) => api.post('/api/v1/study-daily/plan/item/update', payload, NO_RETRY),
  removeItem: (payload: { date: string; item_id: string }) =>
    api.post('/api/v1/study-daily/plan/item/remove', payload, NO_RETRY),
};

/* ============================== 商城（食物 / 礼物） ============================== */

export interface ShopItem {
  id: string;
  name: string;
  description: string;
  price: number;
  category: 'food' | 'gift' | 'toy' | 'book' | 'clothing' | 'tech' | 'luxury';
  sub_type?: string;
  icon?: string;
  nutrition?: {
    hunger?: number;
    thirst?: number;
    energy?: number;
    health?: number;
  } | null;
  effect_desc?: string;
  buff_desc?: string;
}

export interface ShopMenu {
  items: ShopItem[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  coins?: number;
  unlimited_coins?: boolean;
}

export interface InventoryEntry {
  item_id: string;
  item_name: string;
  category?: string;
  quantity: number;
  recipient?: string;
  effect_desc?: string;
  food_id?: string;
  name?: string;
}

export const shopApi = {
  menu: (params: { category?: string; page?: number; page_size?: number }) =>
    api.get('/api/v1/food/shop/menu', params, NO_RETRY),
  buy: (itemId: string, quantity: number, recipient: string) =>
    api.post(
      `/api/v1/food/buy/${encodeURIComponent(itemId)}?quantity=${quantity}&recipient=${encodeURIComponent(
        recipient,
      )}`,
      undefined,
      NO_RETRY,
    ),
  eat: (foodId: string, params: { recipient?: string; from_inventory?: boolean } = {}) =>
    api.post(
      `/api/v1/food/eat/${encodeURIComponent(foodId)}?from_inventory=${
        params.from_inventory === false ? 'false' : 'true'
      }&recipient=${encodeURIComponent(params.recipient || '')}`,
      undefined,
      NO_RETRY,
    ),
  foodInventory: () => api.get('/api/v1/food/inventory', undefined, NO_RETRY),
  giftInventory: () => api.get('/api/v1/food/gift-inventory', undefined, NO_RETRY),
  useGift: (itemId: string, recipient: string) =>
    api.post(
      `/api/v1/food/use-gift/${encodeURIComponent(itemId)}?recipient=${encodeURIComponent(recipient)}`,
      undefined,
      NO_RETRY,
    ),
};
