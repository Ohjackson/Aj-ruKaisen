import { useState } from "react";

export default function JoinModal({ defaultName = "", disabled, onJoin }) {
  const [name, setName] = useState(defaultName);

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal join-modal">
        <header>
          <h2>에저회전에 접속</h2>
        </header>
        <div className="modal-body">
          <p>Azure 의식에 참여할 닉네임을 입력하세요.</p>
          <form
            className="join-form-vertical"
            onSubmit={(event) => {
              event.preventDefault();
              const value = name.trim();
              if (!value) return;
              onJoin(value);
            }}
          >
            <label htmlFor="join-name">닉네임</label>
            <input
              id="join-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="예: AzureMage"
              disabled={disabled}
              autoFocus
            />
            <button type="submit" className="primary" disabled={disabled || !name.trim()}>
              의식에 참여
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
