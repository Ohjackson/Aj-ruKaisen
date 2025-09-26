function formatMs(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function Timer({ phase, round, timerMs, connectionStatus }) {
  return (
    <div className="timer">
      <span className="badge">라운드 {round || 0}</span>
      <span className={`badge ${phase}`}>상태: {phase}</span>
      <span className="badge">타이머: {formatMs(timerMs)}</span>
      <span className={`badge ${connectionStatus}`}>{connectionStatus}</span>
    </div>
  );
}
