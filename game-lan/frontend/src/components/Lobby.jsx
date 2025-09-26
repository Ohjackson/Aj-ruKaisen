import { useEffect, useState } from "react";

export default function Lobby({ onJoin, initialName = "", connectionStatus, lastError }) {
  const [name, setName] = useState(initialName);

  useEffect(() => {
    setName(initialName);
  }, [initialName]);

  const disabled = connectionStatus !== "connected";

  return (
    <section className="lobby">
      <h2>닉네임으로 입장</h2>
      <form
        className="lobby-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!name.trim()) return;
          onJoin(name.trim());
        }}
      >
        <label htmlFor="nickname">닉네임</label>
        <input
          id="nickname"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="닉네임을 입력하세요"
          disabled={disabled}
          autoFocus
        />
        <button type="submit" disabled={disabled || !name.trim()}>
          입장
        </button>
      </form>
      <p className="lobby-status">상태: {connectionStatus}</p>
      {lastError && <p className="error">{lastError}</p>}
    </section>
  );
}
