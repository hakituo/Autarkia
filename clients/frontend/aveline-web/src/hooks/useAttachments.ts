// 多选附件队列：先本地排队预览，发送时统一上传，再把路径拼进一条消息。
//
// 单张图片走原来的「上传 -> 视觉识别 -> 自动追问」链路；多选场景不逐个触发，
// 否则一次选 3 张会发出 3 条消息、3 次模型调用。这里统一成「一条消息带多个
// 媒体标记」，与后端 `[图片: URL]` / `[视频: URL]` 的约定保持一致。
import { useCallback, useState } from 'react';
import { api } from '../api/apiService';
import type { AttachmentDraft } from '../types/features';

const MAX_ATTACHMENTS = 9;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|heic)$/i;

const readPreview = (file: File): Promise<string> =>
  new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve('');
    reader.onload = () => resolve(String(reader.result || ''));
    reader.readAsDataURL(file);
  });

const isImageFile = (file: File): boolean =>
  String(file.type || '').toLowerCase().startsWith('image/') || IMAGE_EXT.test(file.name);

export interface AttachmentQueue {
  attachments: AttachmentDraft[];
  addFiles: (files: FileList | File[]) => Promise<{ added: number; skipped: number }>;
  remove: (id: string) => void;
  clear: () => void;
  uploading: boolean;
  uploadAll: () => Promise<{ paths: string[]; failed: string[] }>;
  buildMessage: (paths: string[], userText: string) => string;
}

export function useAttachments(): AttachmentQueue {
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [uploading, setUploading] = useState(false);

  const addFiles = useCallback(async (files: FileList | File[]) => {
    const incoming = Array.from(files || []);
    const room = Math.max(0, MAX_ATTACHMENTS - attachments.length);
    const accepted: AttachmentDraft[] = [];

    for (const file of incoming.slice(0, room)) {
      const kind: AttachmentDraft['kind'] = isImageFile(file) ? 'image' : 'file';
      const preview = kind === 'image' ? await readPreview(file) : '';
      accepted.push({
        id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        preview,
        kind,
      });
    }

    if (accepted.length > 0) {
      setAttachments((prev) => [...prev, ...accepted].slice(0, MAX_ATTACHMENTS));
    }
    return { added: accepted.length, skipped: incoming.length - accepted.length };
  }, [attachments.length]);

  const remove = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => setAttachments([]), []);

  const uploadAll = useCallback(async () => {
    if (attachments.length === 0) return { paths: [], failed: [] };
    setUploading(true);
    const paths: string[] = [];
    const failed: string[] = [];
    for (const item of attachments) {
      try {
        const res: any = await api.upload(item.file);
        const path = String(res?.data?.file_path || '');
        if (res?.status === 'success' && path) {
          paths.push(`${path}::${item.file.name}::${item.kind}`);
        } else {
          failed.push(item.file.name);
        }
      } catch {
        failed.push(item.file.name);
      }
    }
    setUploading(false);
    return { paths, failed };
  }, [attachments]);

  const buildMessage = useCallback((paths: string[], userText: string) => {
    const markers = paths.map((entry) => {
      const [rawPath, name, kind] = entry.split('::');
      const url = rawPath.startsWith('/') ? rawPath : `/${rawPath}`;
      return kind === 'image' ? `[图片: ${url}]` : `[文件: ${name}] ${url}`;
    });
    return [userText.trim(), ...markers].filter(Boolean).join('\n');
  }, []);

  return { attachments, addFiles, remove, clear, uploading, uploadAll, buildMessage };
}

export default useAttachments;
