import { useState } from "react";

export default function HostPanel({ onSubmit, pendingRound }) {
  const [secret, setSecret] = useState("");

  return (
    <section className="host-panel">
      <h2>호스트 제시어 설정</h2>
      <p className="muted">제시어는 서버에만 저장되며 절대 공개되지 않습니다.</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!secret.trim()) return;
          onSubmit(secret.trim());
          setSecret("");
        }}
      >
        <label htmlFor="host-secret" className="sr-only">
          제시어 입력
        </label>
        <input
          id="host-secret"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          placeholder="이번 라운드 비밀 제시어"
        />
        <button type="submit" disabled={!secret.trim()}>
          제시어 등록
        </button>
      </form>
      {pendingRound && <p className="hint-text">라운드 {pendingRound} 준비 완료!</p>}
    </section>
  );
}
