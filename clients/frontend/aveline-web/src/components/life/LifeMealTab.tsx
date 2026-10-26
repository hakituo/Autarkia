import React, { useMemo } from 'react';
import { Utensils } from 'lucide-react';
import type { HealthSnapshot, NutritionEntryRaw } from '../../api/extendedApi';
import { LifeEmpty, LifeSection, Pill, StatGrid, StatTile } from './LifeUi';
import { formatClock, formatNumber, type LifeNutrition, type LifePortrait } from './types';

const MEAL_LABEL: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
  '1': '早餐',
  '2': '午餐',
  '3': '晚餐',
  '4': '加餐',
};

function mealLabel(raw?: string | null): string {
  if (!raw) return '未分类';
  const key = String(raw).trim().toLowerCase();
  return MEAL_LABEL[key] || String(raw);
}

const MICRO_FIELDS: Array<{ key: keyof NutritionEntryRaw; label: string; unit: string }> = [
  { key: 'dietary_fiber', label: '纤维', unit: 'g' },
  { key: 'sugar', label: '糖', unit: 'g' },
  { key: 'sodium', label: '钠', unit: 'mg' },
  { key: 'potassium', label: '钾', unit: 'mg' },
  { key: 'calcium', label: '钙', unit: 'mg' },
  { key: 'iron', label: '铁', unit: 'mg' },
  { key: 'vitamin_a', label: '维A', unit: 'μg' },
  { key: 'vitamin_c', label: '维C', unit: 'mg' },
  { key: 'cholesterol', label: '胆固醇', unit: 'mg' },
  { key: 'saturated_fat', label: '饱和脂肪', unit: 'g' },
  { key: 'trans_fat', label: '反式脂肪', unit: 'g' },
];

export const LifeMealTab: React.FC<{
  nutrition: LifeNutrition;
  health: HealthSnapshot | null;
  portrait: LifePortrait | null;
}> = ({ nutrition, health, portrait }) => {
  const entries = useMemo(
    () =>
      (nutrition.nutrition_entries || [])
        .slice()
        .sort((a, b) => String(b.time || '').localeCompare(String(a.time || ''))),
    [nutrition.nutrition_entries],
  );

  const sums = useMemo(() => {
    const acc = { calories: 0, protein: 0, carbs: 0, fat: 0 };
    entries.forEach((entry) => {
      acc.calories += Number(entry.calories || 0);
      acc.protein += Number(entry.protein || 0);
      acc.carbs += Number(entry.carbs || 0);
      acc.fat += Number(entry.fat || 0);
    });
    return acc;
  }, [entries]);

  const portraitMeals = portrait?.meals || [];
  const hasEntries = entries.length > 0;
  const calories = sums.calories || Number(health?.nutrition_calories || 0);
  const calorieGoal = Number(health?.nutrition_goal_calories || 0);
  const protein = sums.protein || Number(health?.nutrition_protein || 0);
  const carbs = sums.carbs || Number(health?.nutrition_carbs || 0);
  const fat = sums.fat || Number(health?.nutrition_fat || 0);

  return (
    <div className="space-y-3">
      <LifeSection
        title="今日营养"
        icon={<Utensils size={16} />}
        subtitle={nutrition.date ? `${nutrition.date}` : '按日汇总'}
        action={
          calorieGoal > 0 ? (
            <Pill tone={calories > calorieGoal ? 'amber' : 'emerald'}>
              {Math.round(calories)} / {Math.round(calorieGoal)} kcal
            </Pill>
          ) : undefined
        }
      >
        <StatGrid columns="grid-cols-2 sm:grid-cols-4">
          <StatTile label="热量" value={Math.round(calories)} unit="kcal" tone="amber" />
          <StatTile label="蛋白质" value={formatNumber(protein, 1)} unit="g" tone="emerald" />
          <StatTile label="碳水" value={formatNumber(carbs, 1)} unit="g" tone="sky" />
          <StatTile label="脂肪" value={formatNumber(fat, 1)} unit="g" />
        </StatGrid>
      </LifeSection>

      <LifeSection title="逐条饮食" subtitle="含设备同步与 AI 照片记录">
        {!hasEntries ? (
          <LifeEmpty
            icon={<Utensils size={32} />}
            title="今天还没有饮食记录"
            hint="饮食明细来自安卓端 Samsung Health 同步或 AI 照片识别。"
            action={
              portraitMeals.length > 0 ? (
                <div className="mt-3 w-full space-y-2 text-left">
                  {portraitMeals.slice(-5).reverse().map((meal, index) => (
                    <div
                      key={`${meal.time}-${index}`}
                      className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <div className="text-xs text-white/70 truncate">{meal.content || '饮食记录'}</div>
                        <div className="text-[10px] text-white/25">{meal.type || '未分类'}</div>
                      </div>
                      <span className="text-[10px] text-white/35 tabular-nums shrink-0">
                        {formatClock(meal.time)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : undefined
            }
          />
        ) : (
          <ul className="space-y-2">
            {entries.map((entry, index) => {
              const micros = MICRO_FIELDS.filter((field) => entry[field.key] != null);
              return (
                <li key={`${entry.time}-${entry.title}-${index}`} className="rounded-xl bg-white/5 px-3 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-sm text-white/85 truncate">{entry.title || '未命名食物'}</span>
                        <Pill>{mealLabel(entry.meal_type)}</Pill>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-white/35">
                        <span className="tabular-nums">{formatClock(entry.time)}</span>
                        <span>蛋白 {formatNumber(entry.protein, 1)}g</span>
                        <span>碳水 {formatNumber(entry.carbs, 1)}g</span>
                        <span>脂肪 {formatNumber(entry.fat, 1)}g</span>
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-sm text-amber-200 tabular-nums">
                        {formatNumber(entry.calories)}
                      </div>
                      <div className="text-[10px] text-white/25">kcal</div>
                    </div>
                  </div>
                  {micros.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {micros.map((field) => (
                        <span
                          key={String(field.key)}
                          className="px-1.5 py-0.5 rounded bg-white/5 text-[10px] text-white/40 tabular-nums"
                        >
                          {field.label} {formatNumber(entry[field.key] as number, 1)}
                          {field.unit}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </LifeSection>
    </div>
  );
};
