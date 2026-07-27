import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User } from 'lucide-react';

export const ChatMessage = ({ message }) => {
  const isUser = message.role === 'user';
  const hasError = !isUser && message.status === 'error';

  return (
    <div className={`flex gap-3 my-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${
        isUser ? 'bg-red-600 text-white' : 'bg-slate-200 dark:bg-slate-700 text-red-600 dark:text-red-400'
      }`}>
        {isUser ? <User size={20} /> : <Bot size={20} />}
      </div>

      <div className={`max-w-[85%] md:max-w-[75%] rounded-2xl px-4 py-3 shadow-sm ${
        isUser 
          ? 'bg-red-600 text-white rounded-tr-none' 
          : 'bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-100 border border-slate-200 dark:border-slate-700 rounded-tl-none'
      }`}>
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        ) : (
          <div className="prose dark:prose-invert max-w-none text-sm leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {hasError && (
          <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
            Phản hồi bị gián đoạn.
          </p>
        )}
      </div>
    </div>
  );
};
