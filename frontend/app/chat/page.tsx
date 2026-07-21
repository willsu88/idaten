import { Suspense } from "react";
import { ChatClient } from "@/components/chat/chat-client";

export default function ChatPage() {
  return (
    <Suspense>
      <ChatClient />
    </Suspense>
  );
}
