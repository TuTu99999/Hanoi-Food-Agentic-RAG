import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, Navigation, User } from 'lucide-react';
import {
  isExternalMarkdownLink,
  isGoogleMapsDirectionsLink,
  placeDirectionsNextToVenues,
  sanitizeMarkdownImage,
  sanitizeMarkdownLink,
} from '../lib/markdown';

const MarkdownLink = ({ href, children }) => {
  const safeHref = sanitizeMarkdownLink(href);
  if (!safeHref) {
    return <span>{children}</span>;
  }

  const external = isExternalMarkdownLink(safeHref);
  const isDirections = isGoogleMapsDirectionsLink(safeHref);
  return (
    <a
      href={safeHref}
      rel={external ? 'noopener noreferrer nofollow' : undefined}
      target={external ? '_blank' : undefined}
      className={isDirections
        ? 'not-prose inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-2 text-xs font-semibold text-white no-underline hover:bg-red-700'
        : undefined}
      title={isDirections ? 'Mở Google Maps để chỉ đường từ vị trí hiện tại' : undefined}
    >
      {isDirections && <Navigation size={14} aria-hidden="true" />}
      {isDirections ? 'Chỉ đường trên Google Maps' : children}
    </a>
  );
};

const MarkdownImage = ({ src, alt }) => {
  const safeSrc = sanitizeMarkdownImage(src);
  if (!safeSrc) {
    return alt ? <span>{alt}</span> : null;
  }

  return (
    <img
      src={safeSrc}
      alt={alt || ''}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={(event) => { event.currentTarget.hidden = true; }}
    />
  );
};

const markdownComponents = {
  a: MarkdownLink,
  img: MarkdownImage,
};

export const AssistantMarkdown = ({ content }) => (
  <ReactMarkdown
    components={markdownComponents}
    remarkPlugins={[remarkGfm]}
  >
    {placeDirectionsNextToVenues(content)}
  </ReactMarkdown>
);

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
            <AssistantMarkdown content={message.content} />
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
