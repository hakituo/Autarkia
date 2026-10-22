import React from 'react';
import { FileText, Loader2, X } from 'lucide-react';
import type { AttachmentDraft } from '../../types/features';

interface AttachmentTrayProps {
  attachments: AttachmentDraft[];
  uploading?: boolean;
  onRemove: (id: string) => void;
  onClear?: () => void;
}

/** 输入框上方的多选附件预览条。 */
export const AttachmentTray: React.FC<AttachmentTrayProps> = ({
  attachments,
  uploading,
  onRemove,
  onClear,
}) => {
  if (attachments.length === 0) return null;

  return (
    <div className="px-4 pt-2">
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wider text-white/30 flex items-center gap-1.5">
          {uploading ? <Loader2 size={10} className="animate-spin" /> : null}
          待发送 {attachments.length} 个附件
        </span>
        {onClear && (
          <button
            onClick={onClear}
            className="text-[10px] text-white/30 hover:text-white/70 transition-colors"
          >
            清空
          </button>
        )}
      </div>
      <div className="flex gap-2 overflow-x-auto custom-scrollbar pb-1">
        {attachments.map((item) => (
          <div
            key={item.id}
            className="relative group shrink-0 w-16 h-16 rounded-lg overflow-hidden border border-white/10 bg-black/40 flex items-center justify-center"
            title={item.file.name}
          >
            {item.kind === 'image' && item.preview ? (
              <img src={item.preview} alt={item.file.name} className="w-full h-full object-cover" />
            ) : (
              <div className="flex flex-col items-center gap-1 px-1">
                <FileText size={16} className="text-white/40" />
                <span className="text-[8px] text-white/40 truncate w-full text-center">
                  {item.file.name}
                </span>
              </div>
            )}
            <button
              onClick={() => onRemove(item.id)}
              className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-black/70 text-white/70 hover:text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label={`移除 ${item.file.name}`}
            >
              <X size={9} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};

export default AttachmentTray;
