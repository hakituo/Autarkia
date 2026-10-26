import React from 'react';

type Tone = 'default' | 'emerald' | 'amber' | 'rose' | 'sky';

const TONE_TEXT: Record<Tone, string> = {
  default: 'text-white/90',
  emerald: 'text-emerald-300',
  amber: 'text-amber-300',
  rose: 'text-rose-300',
  sky: 'text-sky-300',
};

const TONE_BG: Record<Tone, string> = {
  default: 'bg-white/10',
  emerald: 'bg-emerald-400',
  amber: 'bg-amber-400',
  rose: 'bg-rose-400',
  sky: 'bg-sky-400',
};

export const LifeSection: React.FC<{
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, subtitle, icon, action, children }) => (
  <section className="glass-card rounded-2xl border border-white/10 overflow-hidden">
    <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/5">
      <div className="flex items-center gap-2 min-w-0">
        {icon && <span className="text-white/40 shrink-0">{icon}</span>}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white/85 truncate">{title}</h3>
          {subtitle && <p className="text-[11px] text-white/30 truncate">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </header>
    <div className="p-4">{children}</div>
  </section>
);

export const StatTile: React.FC<{
  label: string;
  value: React.ReactNode;
  unit?: string;
  hint?: string;
  tone?: Tone;
}> = ({ label, value, unit, hint, tone = 'default' }) => (
  <div className="rounded-xl bg-white/5 border border-white/5 px-3 py-2.5 min-w-0">
    <div className="text-[10px] uppercase tracking-wider text-white/30 truncate">{label}</div>
    <div className="flex items-baseline gap-1 mt-1 min-w-0">
      <span className={`text-lg font-semibold tabular-nums truncate ${TONE_TEXT[tone]}`}>{value}</span>
      {unit && <span className="text-[11px] text-white/30 shrink-0">{unit}</span>}
    </div>
    {hint && <div className="text-[10px] text-white/25 mt-0.5 truncate">{hint}</div>}
  </div>
);

export const StatGrid: React.FC<{ children: React.ReactNode; columns?: string }> = ({
  children,
  columns = 'grid-cols-2 sm:grid-cols-3',
}) => <div className={`grid ${columns} gap-2`}>{children}</div>;

export const LifeBar: React.FC<{ ratio: number; tone?: Tone; height?: string }> = ({
  ratio,
  tone = 'emerald',
  height = 'h-2',
}) => {
  const safe = Number.isFinite(ratio) ? Math.max(0, Math.min(1, ratio)) : 0;
  return (
    <div className={`w-full ${height} rounded-full bg-white/8 overflow-hidden`}>
      <div
        className={`h-full rounded-full transition-all duration-500 ${TONE_BG[tone]}`}
        style={{ width: `${safe * 100}%` }}
      />
    </div>
  );
};

export const LifeEmpty: React.FC<{
  title: string;
  hint?: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}> = ({ title, hint, icon, action }) => (
  <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
    {icon && <div className="text-white/10">{icon}</div>}
    <div className="text-sm text-white/50">{title}</div>
    {hint && <div className="text-[11px] text-white/25 max-w-sm leading-relaxed">{hint}</div>}
    {action}
  </div>
);

export const LifeLoading: React.FC<{ text?: string }> = ({ text = '加载中…' }) => (
  <div className="flex flex-col items-center justify-center gap-3 py-14">
    <div className="w-8 h-8 border-2 border-emerald-400/20 border-t-emerald-400 rounded-full animate-spin" />
    <div className="text-xs text-white/35">{text}</div>
  </div>
);

export const Pill: React.FC<{ children: React.ReactNode; tone?: Tone }> = ({
  children,
  tone = 'default',
}) => (
  <span
    className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] border ${
      tone === 'default'
        ? 'bg-white/5 text-white/50 border-white/10'
        : tone === 'emerald'
          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
          : tone === 'amber'
            ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
            : tone === 'rose'
              ? 'bg-rose-500/10 text-rose-300 border-rose-500/20'
              : 'bg-sky-500/10 text-sky-300 border-sky-500/20'
    }`}
  >
    {children}
  </span>
);
