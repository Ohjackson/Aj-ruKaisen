export default function Scoreboard({ roomState, youId }) {
  const players = (roomState?.players || []).slice().sort((a, b) => b.score - a.score);

  return (
    <div className="scoreboard">
      <h2>스코어보드</h2>
      <ul>
        {players.map((player, index) => (
          <li key={player.id} className={player.id === youId ? "me" : ""}>
            <span className="rank">{index + 1}</span>
            <span className="name">
              {player.name} {player.isHost ? "(방장)" : ""}
              {!player.connected ? " · 오프라인" : ""}
            </span>
            <span className="score">{player.score}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
