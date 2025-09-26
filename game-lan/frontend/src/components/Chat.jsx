import { useEffect, useRef, useState } from "react";

const formatTime = (ts) => {
  if (!ts) return "--:--";
  const date = new Date(ts);
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
};

export default function Chat({ messages, onSend, disabled, placeholder }) {
  const [draft, setDraft] = useState("");
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
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
    <section className={`chat-panel ${disabled ? "disabled" : ""}`}>
      <header>
        <h2>채팅</h2>
      </header>
      <div className="chat-log" ref={logRef}>
        {messages.map((msg) => (
          <p key={`${msg.ts}-${msg.playerId}`}>
            <span className="chat-time">{formatTime(msg.ts)}</span>
            <span className="chat-name">[{msg.name || msg.playerId}]</span> {msg.message}
          </p>
        ))}
        {!messages.length && <p className="chat-empty">메시지가 없습니다.</p>}
      </div>
      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={placeholder}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || !draft.trim()}>
          전송
        </button>
      </form>
    </section>
  );
}
