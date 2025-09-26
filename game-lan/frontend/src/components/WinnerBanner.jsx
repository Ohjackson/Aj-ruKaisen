export default function WinnerBanner({ winner }) {
  if (!winner) return null;
  return (
    <div className="winner-banner" role="status" aria-live="assertive">
      <div className="winner-content">
        <h2>Winner!</h2>
        <p>{winner.name}</p>
        <p className="winner-score">총점 {winner.score}</p>
      </div>
    </div>
  );
}
