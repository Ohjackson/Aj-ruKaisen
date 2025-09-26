import { useState } from "react";

export default function TurnPanel({ canSubmit, isMyTurn, phase, onSubmit, lastError }) {
  const [value, setValue] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    if (!value.trim()) return;
    onSubmit(value.trim());
    setValue("");
  };

  return (
    <section className="turn-panel">
      <h2>턴 제출</h2>
      <p className="muted">
        {phase === "collecting"
          ? isMyTurn
            ? "당신의 차례입니다! 단어 1개를 제출하세요."
            : "다른 플레이어의 제출을 기다리는 중입니다."
          : "라운드가 종료될 때까지 대기하세요."}
      </p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="turn-word" className="sr-only">
          단어 입력
        </label>
        <input
          id="turn-word"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="단어 1개"
          disabled={!canSubmit}
          autoComplete="off"
        />
        <button type="submit" disabled={!canSubmit || !value.trim()}>
          제출
        </button>
      </form>
      {lastError && <p className="error">{lastError}</p>}
    </section>
  );
}
