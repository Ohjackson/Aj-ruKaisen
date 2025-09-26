import { useEffect, useRef, useState } from "react";

export default function Chat({ messages, onSend, disabled }) {
  const [draft, setDraft] = useState("");
  const bottomRef = useRef(null);

  useEffect(() => {
    if (bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  const handleSubmit = (event) => {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    onSend(value);
    setDraft("");
  };

  return (
    <div className="chat">
      <h2>공개 채팅</h2>
      <div className="chat-log">
        {messages.map((msg) => (
          <p key={msg.ts + msg.playerId}>
            <span className="chat-name">[{msg.name}]</span> {msg.message}
          </p>
        ))}
        <div ref={bottomRef} />
      </div>
      <form className="chat-form" onSubmit={handleSubmit}>
        <label htmlFor="chat-input" className="sr-only">
          채팅 입력
        </label>
        <input
          id="chat-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="메시지 입력"
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !draft.trim()}>
          전송
        </button>
      </form>
    </div>
  );
}
