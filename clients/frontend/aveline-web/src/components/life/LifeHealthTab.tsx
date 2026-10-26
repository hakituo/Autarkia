import React from 'react';
import { Activity, AlertTriangle, Footprints, HeartPulse, Moon, Scale, ShieldCheck } from 'lucide-react';
import type { HealthSnapshot } from '../../api/extendedApi';
import { LifeBar, LifeEmpty, LifeSection, Pill, StatGrid, StatTile } from './LifeUi';
import { formatClock, formatMinutes, formatNumber, formatPercent } from './types';

const SOURCE_LABEL: Record<string, string> = {
  samsung_health: 'Samsung Health',
  health_connect: 'Health Connect',
  wear_os: 'Wear OS',
};

const SIGN_LABEL: Record<string, string> = {
  none: '无异常',
  normal: '正常',
  unknown: '未知',
  low: '偏低',
  high: '偏高',
  possible: '可能有征兆',
  detected: '检测到异常',
};

function signText(value?: string): { text: string; tone: 'emerald' | 'amber' | 'rose' | 'default' } {
  if (!value) return { text: '暂无数据', tone: 'default' };
  const key = String(value).toLowerCase();
  const text = SIGN_LABEL[key] || value;
  if (key.includes('none') || key === 'normal') return { text, tone: 'emerald' };
  if (key.includes('possible') || key.includes('detect') || key === 'high' || key === 'low') {
    return { text, tone: 'amber' };
  }
  return { text, tone: 'default' };
}

export const LifeHealthTab: React.FC<{ health: HealthSnapshot | null }> = ({ health }) => {
  if (!health) {
    return (
      <LifeEmpty
        icon={<HeartPulse size={40} />}
        title="暂无健康数据"
        hint="健康数据由安卓端的 Samsung Health / 穿戴设备同步到后端。同步一次后，这里就能看到活动、睡眠与身体成分。"
      />
    );
  }

  const steps = health.steps_today ?? health.steps;
  const stepsGoal = health.steps_goal;
  const bmi =
    health.weight_kg && health.height_m && health.height_m > 0
      ? health.weight_kg / (health.height_m * health.height_m)
      : null;

  const sleepStages = [
    { label: '清醒', value: health.sleep_stage_awake_minutes, tone: 'amber' as const },
    { label: '浅睡', value: health.sleep_stage_light_minutes, tone: 'sky' as const },
    { label: '深睡', value: health.sleep_stage_deep_minutes, tone: 'emerald' as const },
    { label: 'REM', value: health.sleep_stage_rem_minutes, tone: 'default' as const },
  ].filter((stage) => stage.value != null);

  const apnea = signText(health.sleep_apnea_sign);
  const rhythm = signText(health.irregular_heart_rhythm);
  const hasWarning = apnea.tone !== 'emerald' || rhythm.tone !== 'emerald';
  const source = health.source ? SOURCE_LABEL[health.source] || health.source : '未知来源';

  return (
    <div className="space-y-3">
      <LifeSection title="今日活动" icon={<Footprints size={16} />} subtitle="步数 / 热量 / 距离">
        <div className="space-y-3">
          <div>
            <div className="flex items-end justify-between mb-1.5">
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-semibold tabular-nums text-emerald-300">
                  {formatNumber(steps)}
                </span>
                <span className="text-[11px] text-white/30">步</span>
              </div>
              <span className="text-[11px] text-white/30">
                {stepsGoal ? `目标 ${formatNumber(stepsGoal)} 步` : '未设置目标'}
              </span>
            </div>
            <LifeBar ratio={stepsGoal ? (steps || 0) / stepsGoal : 0} />
          </div>
          <StatGrid>
            <StatTile
              label="活动热量"
              value={formatNumber(health.active_calories_burned)}
              unit="kcal"
              hint={health.active_calories_goal ? `目标 ${formatNumber(health.active_calories_goal)}` : undefined}
              tone="amber"
            />
            <StatTile label="总消耗" value={formatNumber(health.total_calories_burned)} unit="kcal" />
            <StatTile
              label="活动时长"
              value={formatNumber(health.active_time_minutes)}
              unit="分钟"
              hint={
                health.active_time_goal_minutes
                  ? `目标 ${formatNumber(health.active_time_goal_minutes)} 分钟`
                  : undefined
              }
            />
            <StatTile label="总距离" value={formatNumber(health.total_distance_km, 2)} unit="km" />
            <StatTile label="爬楼层数" value={formatNumber(health.floors_climbed)} unit="层" />
            <StatTile label="能量评分" value={formatNumber(health.energy_score)} hint="0-100" tone="emerald" />
          </StatGrid>
        </div>
      </LifeSection>

      <LifeSection title="睡眠" icon={<Moon size={16} />} subtitle="时长 / 分期 / 得分">
        <div className="space-y-3">
          <StatGrid>
            <StatTile label="睡眠时长" value={formatMinutes(health.sleep_minutes)} tone="sky" />
            <StatTile label="睡眠得分" value={formatNumber(health.sleep_score)} hint="0-100" tone="emerald" />
            <StatTile label="入睡" value={formatClock(health.sleep_start_time)} />
            <StatTile label="起床" value={formatClock(health.sleep_end_time)} />
          </StatGrid>
          {sleepStages.length > 0 ? (
            <div className="space-y-1.5">
              {sleepStages.map((stage) => {
                const total = sleepStages.reduce((sum, item) => sum + (item.value || 0), 0);
                const ratio = total > 0 ? (stage.value || 0) / total : 0;
                return (
                  <div key={stage.label} className="flex items-center gap-3">
                    <span className="w-10 text-[11px] text-white/40 shrink-0">{stage.label}</span>
                    <div className="flex-1">
                      <LifeBar ratio={ratio} tone={stage.tone} height="h-1.5" />
                    </div>
                    <span className="w-16 text-right text-[11px] text-white/45 tabular-nums shrink-0">
                      {formatNumber(stage.value)} 分
                    </span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-[11px] text-white/25">未同步睡眠分期数据</div>
          )}
        </div>
      </LifeSection>

      <LifeSection title="身体成分" icon={<Scale size={16} />} subtitle="体重 / 体脂 / 肌肉">
        <StatGrid>
          <StatTile label="体重" value={formatNumber(health.weight_kg, 1)} unit="kg" tone="emerald" />
          <StatTile label="身高" value={formatNumber(health.height_m, 2)} unit="m" />
          <StatTile label="BMI" value={bmi ? formatNumber(bmi, 1) : '--'} />
          <StatTile label="体脂率" value={formatPercent(health.body_fat_percent)} tone="amber" />
          <StatTile label="骨骼肌率" value={formatPercent(health.skeletal_muscle_percent)} />
          <StatTile label="肌肉量" value={formatNumber(health.muscle_mass, 1)} unit="kg" />
          <StatTile label="脂肪量" value={formatNumber(health.body_fat_mass, 1)} unit="kg" />
          <StatTile label="去脂体重" value={formatNumber(health.fat_free_mass, 1)} unit="kg" />
          <StatTile label="骨骼肌量" value={formatNumber(health.skeletal_muscle_mass, 1)} unit="kg" />
          <StatTile label="总体水分" value={formatNumber(health.total_body_water, 1)} unit="kg" />
          <StatTile label="基础代谢" value={formatNumber(health.basal_metabolic_rate)} unit="kcal" />
        </StatGrid>
      </LifeSection>

      <LifeSection title="生命体征" icon={<Activity size={16} />} subtitle="心率 / 血氧 / 体温">
        <StatGrid>
          <StatTile
            label="心率"
            value={formatNumber(health.heart_rate)}
            unit="bpm"
            hint={health.heart_rate_timestamp ? formatClock(health.heart_rate_timestamp) : undefined}
            tone="rose"
          />
          <StatTile label="血氧" value={formatPercent(health.blood_oxygen ?? undefined, 0)} />
          <StatTile label="皮温" value={formatNumber(health.skin_temperature, 1)} unit="°C" />
          <StatTile label="体温" value={formatNumber(health.body_temperature, 1)} unit="°C" />
          <StatTile
            label="血压"
            value={
              health.blood_pressure_systolic && health.blood_pressure_diastolic
                ? `${formatNumber(health.blood_pressure_systolic)}/${formatNumber(health.blood_pressure_diastolic)}`
                : '--'
            }
            unit="mmHg"
          />
          <StatTile label="血糖" value={formatNumber(health.blood_glucose, 1)} unit="mmol/L" />
        </StatGrid>
      </LifeSection>

      <LifeSection
        title="健康预警"
        icon={<ShieldCheck size={16} />}
        subtitle="睡眠呼吸 / 心律"
        action={<Pill tone={hasWarning ? 'amber' : 'emerald'}>{hasWarning ? '需留意' : '正常'}</Pill>}
      >
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-3 py-2">
            <span className="text-xs text-white/50">睡眠呼吸暂停征兆</span>
            <Pill tone={apnea.tone}>{apnea.text}</Pill>
          </div>
          <div className="flex items-center justify-between gap-3 rounded-xl bg-white/5 px-3 py-2">
            <span className="text-xs text-white/50">心律不齐通知</span>
            <Pill tone={rhythm.tone}>{rhythm.text}</Pill>
          </div>
          {hasWarning && (
            <div className="flex items-start gap-2 text-[11px] text-amber-200/70 leading-relaxed">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>预警数据来自穿戴设备，仅供参考，不作为医疗诊断依据。</span>
            </div>
          )}
        </div>
      </LifeSection>

      <div className="flex items-center justify-between px-1 text-[10px] text-white/25">
        <span>数据来源：{source}</span>
        <span>采集于 {health.collected_at ? formatClock(health.collected_at) : '--'}</span>
      </div>
    </div>
  );
};
