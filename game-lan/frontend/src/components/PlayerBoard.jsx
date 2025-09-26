export default function PlayerBoard({ players = [] }) {
  if (!players.length) {
    return (
      <div className="player-board empty">
        <p>아직 플레이어가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="player-board">
      {players.map((player) => (
        <div key={player.id} className={`player-card ${player.ready ? "ready" : ""} ${player.connected ? "" : "offline"}`}>
          <div className="player-card-header">
            <span className="player-name">{player.name}</span>
            {player.isHost ? <span className="badge host">HOST</span> : null}
          </div>
          <div className="player-card-body">
            <span className="player-score">{player.score} pts</span>
            <span className={`ready-indicator ${player.ready ? "on" : "off"}`}>
              {player.ready ? "READY" : "WAIT"}
            </span>
          </div>
          {!player.connected ? <p className="player-status">연결 끊김</p> : null}
        </div>
      ))}
    </div>
  );
}
