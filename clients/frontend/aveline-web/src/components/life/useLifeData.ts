import { useCallback, useEffect, useState } from 'react';
import { dailyApi, healthApi } from '../../api/extendedApi';
import { EMPTY_NUTRITION, todayStr, type LifeData } from './types';

/**
 * 汇总生活模块三份数据源：
 * - /context/health/sync/latest  穿戴设备最新快照（健康 Tab）
 * - /context/daily/portrait/today 作息 / 学习 / 镜像数据（日程 Tab）
 * - /context/health/nutrition     逐条饮食与饮水（饮水 / 餐食 Tab）
 *
 * 任何一个接口失败都不影响其余 Tab 展示，因此用 Promise.allSettled。
 */
export function useLifeData(date: string = todayStr()) {
  const [data, setData] = useState<LifeData>({
    health: null,
    portrait: null,
    nutrition: EMPTY_NUTRITION,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [healthRes, portraitRes, nutritionRes] = await Promise.allSettled([
      healthApi.latest(),
      dailyApi.portraitToday(),
      healthApi.nutrition(date),
    ]);

    const next: LifeData = {
      health: null,
      portrait: null,
      nutrition: { ...EMPTY_NUTRITION },
    };
    const failures: string[] = [];

    if (healthRes.status === 'fulfilled') {
      // 后端是 success_response(data={path, data: 快照, timestamp})，快照在第二层 data
      const payload = healthRes.value?.data;
      const snapshot = payload?.data ?? payload ?? null;
      next.health = (snapshot && typeof snapshot === 'object' ? snapshot : null) as LifeData['health'];
    } else {
      failures.push('健康快照');
    }

    if (portraitRes.status === 'fulfilled' && portraitRes.value?.status === 'success') {
      next.portrait = portraitRes.value.portrait ?? null;
    } else {
      failures.push('今日画像');
    }

    if (nutritionRes.status === 'fulfilled') {
      const payload = nutritionRes.value?.data ?? {};
      next.nutrition = {
        date: payload.date ?? date,
        nutrition_entries: payload.nutrition_entries ?? [],
        water_intake_entries: payload.water_intake_entries ?? [],
      };
    } else {
      failures.push('饮食记录');
    }

    setData(next);
    // 全部失败才算错误；部分失败由各 Tab 自己展示空态。
    setError(failures.length === 3 ? `加载失败：${failures.join('、')}` : null);
    setLoading(false);
  }, [date]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
