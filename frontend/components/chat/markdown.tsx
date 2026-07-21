"use client";

import ReactMarkdown from "react-markdown";

/** Renders assistant markdown (bold, lists, headings, code) in chat bubbles. */
export function Markdown({ content }: { content: string }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
