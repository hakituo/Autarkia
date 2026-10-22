import React, { useEffect, useMemo, useState } from 'react';
import { ChevronRight, FileText, FolderOpen, Loader2, RefreshCw, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { featureApi } from '../../../api/featureApi';
import type { StudyNoteItem } from '../../../types/features';

interface NoteGroup {
  key: string;
  label: string;
  notes: StudyNoteItem[];
}

const groupKeyOf = (note: StudyNoteItem): string => {
  const source = String(note.path || note.filename || '');
  const match = source.match(/(\d{4})[\/\\](\d{2})(?:[\/\\](\d{2}))?/);
  if (!match) return '未归档';
  return match[3] ? `${match[1]}-${match[2]}-${match[3]}` : `${match[1]}-${match[2]}`;
};

/** 专题笔记树：按日期归档分组，点开读全文（markdown 渲染）。 */
export const NotesTree: React.FC = () => {
  const [notes, setNotes] = useState<StudyNoteItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [active, setActive] = useState<StudyNoteItem | null>(null);
  const [content, setContent] = useState('');
  const [contentLoading, setContentLoading] = useState(false);
  const [query, setQuery] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const list = await featureApi.listStudyNotes();
      setNotes(list);
    } catch (err: any) {
      setError(err?.message || '笔记列表加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const groups = useMemo<NoteGroup[]>(() => {
    const keyword = query.trim().toLowerCase();
    const filtered = keyword
      ? notes.filter((note) =>
          `${note.title || ''}${note.filename}`.toLowerCase().includes(keyword),
        )
      : notes;
    const buckets = new Map<string, StudyNoteItem[]>();
    filtered.forEach((note) => {
      const key = groupKeyOf(note);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(note);
    });
    return Array.from(buckets.entries())
      .map(([key, items]) => ({ key, label: key, notes: items }))
      .sort((a, b) => b.key.localeCompare(a.key));
  }, [notes, query]);

  const openNote = async (note: StudyNoteItem) => {
    setActive(note);
    setContentLoading(true);
    setContent('');
    try {
      const data = await featureApi.readStudyNote(note.filename);
      setContent(String((data as any)?.content || '（空笔记）'));
    } catch (err: any) {
      setContent(`读取失败：${err?.message || '未知错误'}`);
    } finally {
      setContentLoading(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 gap-4">
      <div className="w-64 shrink-0 flex flex-col min-h-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] uppercase tracking-wider text-white/35">
            笔记树 · {notes.length}
          </span>
          <button
            onClick={() => void load()}
            className="p-1 rounded text-white/40 hover:text-white hover:bg-white/10"
            title="刷新"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索笔记标题"
          className="mb-2 w-full bg-black/30 border border-white/10 rounded-lg px-2.5 py-1.5 text-[11px] text-white outline-none focus:border-emerald-500/50"
        />
        <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 pr-1">
          {error && <div className="text-[11px] text-red-300/80 px-1">{error}</div>}
          {!loading && groups.length === 0 && !error && (
            <div className="text-[11px] text-white/30 px-1 py-3">还没有专题笔记</div>
          )}
          {groups.map((group) => (
            <div key={group.key}>
              <div className="flex items-center gap-1 px-1 py-1 text-[10px] text-white/30 font-mono">
                <FolderOpen size={10} /> {group.label}
              </div>
              {group.notes.map((note) => (
                <button
                  key={note.filename}
                  onClick={() => void openNote(note)}
                  className={`w-full flex items-center gap-1.5 px-2 py-1.5 rounded-md text-left text-[11px] transition-colors ${
                    active?.filename === note.filename
                      ? 'bg-emerald-500/15 text-emerald-100'
                      : 'text-white/50 hover:bg-white/5 hover:text-white/80'
                  }`}
                >
                  <FileText size={10} className="shrink-0" />
                  <span className="truncate">{note.title || note.filename}</span>
                  <ChevronRight size={10} className="ml-auto opacity-30 shrink-0" />
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-0 rounded-xl border border-white/10 bg-black/25 flex flex-col min-h-0">
        <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
          <span className="text-xs text-white/70 truncate">
            {active ? active.title || active.filename : '选择一篇笔记'}
          </span>
          {active && (
            <button
              onClick={() => {
                setActive(null);
                setContent('');
              }}
              className="p-1 rounded text-white/35 hover:text-white hover:bg-white/10"
            >
              <X size={12} />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4">
          {contentLoading && (
            <div className="flex items-center gap-2 text-[11px] text-white/40">
              <Loader2 size={12} className="animate-spin" /> 读取中…
            </div>
          )}
          {!contentLoading && !active && (
            <div className="text-[11px] text-white/30">左侧选一篇笔记即可全文阅读</div>
          )}
          {!contentLoading && active && (
            <div className="prose prose-invert prose-sm max-w-none prose-headings:text-white/90 prose-p:text-white/70 prose-code:text-pink-300">
              <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
                {content}
              </ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default NotesTree;
