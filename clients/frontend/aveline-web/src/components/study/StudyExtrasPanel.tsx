import React, { useState } from 'react';
import { BookMarked, CalendarDays, Target } from 'lucide-react';
import NotesTree from './extras/NotesTree';
import DiaryAuthors from './extras/DiaryAuthors';
import VocabSessionSummary from './extras/VocabSessionSummary';

type TabKey = 'notes' | 'diary' | 'vocab';

const TABS: Array<{ key: TabKey; label: string; icon: React.ElementType }> = [
  { key: 'notes', label: '专题笔记', icon: BookMarked },
  { key: 'diary', label: '日记作者', icon: CalendarDays },
  { key: 'vocab', label: '复习会话', icon: Target },
];

/** 学习扩展：笔记树全文阅读、日记按作者筛选、词汇会话总结。 */
const StudyExtrasPanel: React.FC = () => {
  const [tab, setTab] = useState<TabKey>('notes');

  return (
    <div className="flex-1 min-h-0 flex flex-col p-4 gap-3">
      <div className="flex items-center gap-1.5 p-1 rounded-xl bg-black/30 border border-white/5 w-fit">
        {TABS.map((item) => {
          const Icon = item.icon;
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] transition-colors ${
                active
                  ? 'bg-white/10 text-white border border-white/10'
                  : 'text-white/40 hover:text-white/70'
              }`}
            >
              <Icon size={12} />
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="flex-1 min-h-0">
        {tab === 'notes' && <NotesTree />}
        {tab === 'diary' && (
          <div className="h-full overflow-y-auto custom-scrollbar pr-1">
            <DiaryAuthors />
          </div>
        )}
        {tab === 'vocab' && (
          <div className="h-full overflow-y-auto custom-scrollbar pr-1">
            <VocabSessionSummary />
          </div>
        )}
      </div>
    </div>
  );
};

export default StudyExtrasPanel;
