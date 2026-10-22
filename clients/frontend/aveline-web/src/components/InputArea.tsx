import React, { useRef, useState } from 'react';
import { Mic, Send, Image as ImageIcon, Paperclip, Loader2, CloudCheck } from 'lucide-react';
import { api } from '../api/apiService';
import { NativeService, isNative } from '../utils/nativeService';
import AttachmentTray from './chat/AttachmentTray';
import type { AttachmentDraft } from '../types/features';

interface InputAreaProps {
  input: string;
  setInput: (s: string) => void;
  onSend: () => void;
  isTyping: boolean;
  voices: any[];
  selectedVoiceId: string;
  setSelectedVoiceId: (id: string) => void;
  onUpload?: (file: File) => void;
  isMobile?: boolean;
  /** 多选附件队列（传入后启用多选上传，不再逐个文件走 onUpload） */
  attachments?: AttachmentDraft[];
  onAddFiles?: (files: FileList) => void;
  onRemoveAttachment?: (id: string) => void;
  onClearAttachments?: () => void;
  uploadingAttachments?: boolean;
  draftSaved?: boolean;
}

const InputArea = ({ input, setInput, onSend, isTyping, voices, selectedVoiceId, setSelectedVoiceId, onUpload, isMobile, attachments, onAddFiles, onRemoveAttachment, onClearAttachments, uploadingAttachments, draftSaved }: InputAreaProps) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    // Native Recording Logic
    if (isNative) {
      try {
        if (await NativeService.canRecordAudio()) {
          await NativeService.startRecording();
          setIsRecording(true);
          NativeService.hapticImpact(); // Haptic feedback on start
        } else {
          await NativeService.requestPermissions();
          alert('请授予麦克风权限');
        }
      } catch (e) {
        console.error('Native recording failed', e);
        alert('录音启动失败');
      }
      return;
    }

    // Web Recording Logic
    // 检查是否在安全上下文（HTTPS 或 localhost）
    if (!window.isSecureContext && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
      alert('无法访问麦克风：浏览器要求在安全环境（HTTPS 或 localhost）下才能使用麦克风。如果您正在使用 IP 地址访问，请尝试使用 localhost 或为您的域名配置 HTTPS。');
      return;
    }

    // 检查浏览器是否支持 mediaDevices
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('您的浏览器不支持麦克风访问，请更换现代浏览器（如 Chrome, Edge, Firefox）。');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        setIsProcessing(true);
        try {
          const response = await api.transcribeAudio(audioBlob);
          if (response && response.text) {
            setInput(input + (input ? ' ' : '') + response.text);
          }
        } catch (error) {
          console.error('Failed to transcribe audio', error);
        } finally {
          setIsProcessing(false);
          setIsRecording(false);
          stream.getTracks().forEach(track => track.stop());
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error('Error accessing microphone:', err);
      alert('无法访问麦克风，请检查权限设置');
    }
  };

  const stopRecording = async () => {
    if (isNative) {
      if (isRecording) {
        setIsProcessing(true);
        NativeService.hapticImpact(); // Haptic feedback on stop
        try {
          const result = await NativeService.stopRecording();
          if (result.value && result.value.recordDataBase64) {
             const mimeType = result.value.mimeType || 'audio/aac';
             const b64 = result.value.recordDataBase64;
             const response = await fetch(`data:${mimeType};base64,${b64}`);
             const blob = await response.blob();
             
             const apiResponse = await api.transcribeAudio(blob);
             if (apiResponse && apiResponse.text) {
                setInput(input + (input ? ' ' : '') + apiResponse.text);
             }
          }
        } catch (error) {
          console.error('Failed to transcribe native audio', error);
        } finally {
          setIsProcessing(false);
          setIsRecording(false);
        }
      }
      return;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
  };

  const handleMicClick = () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleImageClick = () => {
    imageInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      if (onAddFiles) onAddFiles(files);
      else onUpload?.(files[0]);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      if (onAddFiles) onAddFiles(files);
      else onUpload?.(files[0]);
    }
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
  };

  const vibrate = (ms: number) => {
    try {
      if ('vibrate' in navigator) {
        (navigator as any).vibrate(ms);
      }
    } catch {}
  };

  const handleSendClick = () => {
    if (isTyping || uploadingAttachments) return;
    if (!input.trim() && !(attachments && attachments.length > 0)) return;
    vibrate(8);
    onSend();
  };

  const canUsePressToTalk = Boolean(isMobile);

  const handleMicPressStart = () => {
    if (isProcessing) return;
    if (isRecording) return;
    vibrate(8);
    startRecording();
  };

  const handleMicPressEnd = () => {
    if (isProcessing) return;
    if (!isRecording) return;
    stopRecording();
    vibrate(8);
  };

  return (
    <div className={isMobile ? "p-3 pb-4" : "p-4 pt-2"}>
      <input 
        type="file" 
        ref={fileInputRef} 
        className="hidden" 
        multiple
        onChange={handleFileChange} 
      />
      <input
        type="file"
        ref={imageInputRef}
        className="hidden"
        accept="image/*"
        multiple
        capture={isMobile ? "environment" : undefined}
        onChange={handleImageChange}
      />
      {attachments && onRemoveAttachment && (
        <AttachmentTray
          attachments={attachments}
          uploading={uploadingAttachments}
          onRemove={onRemoveAttachment}
          onClear={onClearAttachments}
        />
      )}
      <div className={`relative flex items-center bg-white/5 rounded-2xl transition-all focus-within:bg-white/10 group ${isMobile ? 'gap-1 px-2 py-1.5' : 'gap-3 px-4 py-2'}`}>
        
        <button 
          className={`rounded-xl text-white/30 hover:text-white hover:bg-white/10 transition-all active:scale-90 flex-shrink-0 ${isMobile ? 'p-1.5' : 'p-2'}`}
          title="上传图片/文件"
          onClick={handleUploadClick}
        >
          <Paperclip size={isMobile ? 18 : 20} />
        </button>

        <button
          className={`rounded-xl text-white/30 hover:text-white hover:bg-white/10 transition-all active:scale-90 flex-shrink-0 ${isMobile ? 'p-1.5' : 'p-2'}`}
          title="拍照/选择图片"
          onClick={handleImageClick}
        >
          <ImageIcon size={isMobile ? 18 : 20} />
        </button>
        
        <button 
          className={`rounded-xl transition-all active:scale-90 flex-shrink-0 ${isRecording ? 'text-red-500 bg-red-500/10 animate-pulse' : 'text-white/30 hover:text-white hover:bg-white/10'} ${isProcessing ? 'opacity-50 cursor-not-allowed' : ''} ${isMobile ? 'p-1.5' : 'p-2'}`}
          title={isRecording ? "停止录音" : "语音输入"}
          onClick={canUsePressToTalk ? undefined : handleMicClick}
          onPointerDown={canUsePressToTalk ? handleMicPressStart : undefined}
          onPointerUp={canUsePressToTalk ? handleMicPressEnd : undefined}
          onPointerCancel={canUsePressToTalk ? handleMicPressEnd : undefined}
          onPointerLeave={canUsePressToTalk ? handleMicPressEnd : undefined}
          disabled={isProcessing}
        >
          {isProcessing ? <Loader2 className="animate-spin" size={isMobile ? 18 : 20} /> : <Mic size={isMobile ? 18 : 20} />}
        </button>

        {!isMobile && <div className="w-[1px] h-6 bg-white/10" />}

        <input 
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isTyping ? "..." : attachments && attachments.length > 0 ? "给这些附件说点什么…" : "Ask Aveline..."}
          disabled={isTyping}
          autoComplete="off"
          className={`flex-1 bg-transparent border-none outline-none text-white text-sm placeholder:text-white/20 disabled:opacity-50 min-w-0 ${isMobile ? 'h-9 px-1' : 'h-10'}`}
        />

        {draftSaved && input.trim() && (
          <span className="hidden sm:flex items-center gap-1 text-[10px] text-white/20 shrink-0" title="草稿已自动保存">
            <CloudCheck size={11} />
          </span>
        )}

        <button 
          onClick={handleSendClick}
          disabled={(!input.trim() && !(attachments && attachments.length > 0)) || isTyping || uploadingAttachments}
          className={`rounded-xl bg-white/10 text-white/70 hover:bg-white/20 hover:text-white disabled:bg-white/5 disabled:text-white/10 disabled:cursor-not-allowed transition-all active:scale-95 flex-none ${isMobile ? 'p-2' : 'p-2.5'}`}
        >
          <Send size={isMobile ? 16 : 18} />
        </button>
      </div>
    </div>
  );
};

export default InputArea;
