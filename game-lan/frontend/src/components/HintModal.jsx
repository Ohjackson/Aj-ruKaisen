export default function HintModal({ result, onClose }) {
  if (!result) return null;
  const { round, hint, score, flags = [] } = result;
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal hint-modal">
        <header>
          <h2>라운드 {round} 힌트</h2>
          <button onClick={onClose} aria-label="닫기">
            ×
          </button>
        </header>
        <div className="modal-body">
          <p className="hint-text">{hint}</p>
          <div className="hint-meta-row">
            <span>점수 {score}</span>
            {flags.length ? <span>플래그: {flags.join(", ")}</span> : null}
          </div>
        </div>
        <footer className="modal-footer">
          <button className="primary" onClick={onClose}>
            확인
          </button>
        </footer>
      </div>
    </div>
  );
}
