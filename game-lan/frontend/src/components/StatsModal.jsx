export default function StatsModal({ stats, onClose }) {
  const rounds = stats?.rounds || [];
  const players = stats?.players || [];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <header>
          <h2>라운드 통계</h2>
          <button onClick={onClose} aria-label="닫기">
            ×
          </button>
        </header>
        <div className="modal-body">
          <table>
            <thead>
              <tr>
                <th>플레이어</th>
                {rounds.map((_, index) => (
                  <th key={index}>R{index + 1}</th>
                ))}
                <th>총점</th>
                <th>순위</th>
              </tr>
            </thead>
            <tbody>
              {players.map((player) => (
                <tr key={player.id}>
                  <td>{player.name}</td>
                  {player.perRound.map((round, idx) => (
                    <td key={idx}>
                      <div className="stat-word">{round.word || "-"}</div>
                      <div className="stat-score">{round.score}점</div>
                      {round.hint ? <div className="stat-hint">{round.hint}</div> : null}
                    </td>
                  ))}
                  <td>{player.total}</td>
                  <td>{player.rank}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
