export default function WinnerBanner({ winner }) {
  if (!winner) return null;
  return (
    <div className="winner-banner" role="status" aria-live="assertive">
      <div className="winner-orb">
        <h2>Azure Champion</h2>
        <p className="winner-name">{winner.name}</p>
        <p className="winner-score">총점 {winner.score}</p>
      </div>
    </div>
  );
}
