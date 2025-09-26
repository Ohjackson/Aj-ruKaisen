import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Lobby from "./components/Lobby.jsx";
import HostPanel from "./components/HostPanel.jsx";
import TurnPanel from "./components/TurnPanel.jsx";
import Chat from "./components/Chat.jsx";
import Scoreboard from "./components/Scoreboard.jsx";
import Timer from "./components/Timer.jsx";
import WinnerBanner from "./components/WinnerBanner.jsx";
import StatsModal from "./components/StatsModal.jsx";
import WSClient from "./lib/ws.js";

const STORAGE_ID = "akPlayerId";
const STORAGE_NAME = "akPlayerName";

const initialPlayerId = () => localStorage.getItem(STORAGE_ID) || "";
const initialPlayerName = () => localStorage.getItem(STORAGE_NAME) || "";

export default function App() {
  const [wsClient, setWsClient] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [playerId, setPlayerId] = useState(initialPlayerId);
  const [playerName, setPlayerName] = useState(initialPlayerName);
  const [isHost, setIsHost] = useState(false);
  const [roomState, setRoomState] = useState(null);
  const [phase, setPhase] = useState("lobby");
  const [currentTurn, setCurrentTurn] = useState(null);
  const [timerMs, setTimerMs] = useState(30000);
  const [chatMessages, setChatMessages] = useState([]);
  const [personalResults, setPersonalResults] = useState({});
  const [roundSummaries, setRoundSummaries] = useState({});
  const [winner, setWinner] = useState(null);
  const [stats, setStats] = useState(null);
  const [statsVisible, setStatsVisible] = useState(false);
  const [pendingSecretRound, setPendingSecretRound] = useState(null);
  const [lastError, setLastError] = useState("");
  const currentRoundRef = useRef(0);

  const handleMessage = useCallback(
    (event) => {
      const { type, payload } = event;
      switch (type) {
        case "joined": {
          setPlayerId(payload.playerId);
          setPlayerName(payload.name);
          setIsHost(payload.isHost);
          localStorage.setItem(STORAGE_ID, payload.playerId);
          localStorage.setItem(STORAGE_NAME, payload.name);
          setLastError("");
          break;
        }
        case "room.state": {
          setRoomState(payload);
          setPhase(payload.phase);
          setTimerMs(payload.timerMs ?? 0);
          currentRoundRef.current = payload.round || 0;
          if (payload.turn) {
            setCurrentTurn(payload.turn);
          }
          break;
        }
        case "turn.next": {
          setCurrentTurn(payload.playerId);
          break;
        }
        case "tick": {
          if (!payload.round || payload.round === currentRoundRef.current) {
            setTimerMs(payload.timerMs);
          }
          break;
        }
        case "round.result:me": {
          setPersonalResults((prev) => ({ ...prev, [payload.round]: payload }));
          break;
        }
        case "round.summary": {
          setRoundSummaries((prev) => ({ ...prev, [payload.round]: payload.entries }));
          break;
        }
        case "phase.changed": {
          setPhase(payload.phase);
          if (payload.phase === "collecting") {
            setWinner(null);
            currentRoundRef.current = payload.round;
          }
          break;
        }
        case "round.started": {
          setPendingSecretRound(null);
          break;
        }
        case "round.ready": {
          setPendingSecretRound(payload.round);
          break;
        }
        case "end.winner": {
          setWinner(payload);
          setStatsVisible(true);
          break;
        }
        case "stats.open": {
          setStats(payload);
          break;
        }
        case "chat.message": {
          setChatMessages((prev) => [...prev.slice(-49), payload]);
          break;
        }
        case "error": {
          setLastError(payload.message || "문제가 발생했습니다.");
          break;
        }
        case "host.secret.accepted": {
          setPendingSecretRound(payload.round);
          break;
        }
        case "pong":
        default:
          break;
      }
    },
    []
  );

  useEffect(() => {
    const path = import.meta.env.VITE_WS_PATH || "/ws";
    const { protocol, host } = window.location;
    const wsProtocol = protocol === "https:" ? "wss" : "ws";
    const url = `${wsProtocol}://${host}${path}`;

    const client = new WSClient(url, {
      onOpen: () => setConnectionStatus("connected"),
      onClose: () => setConnectionStatus("disconnected"),
      onError: () => setConnectionStatus("error"),
      onStateChange: (status) => setConnectionStatus(status),
      onMessage: handleMessage,
    });
    setWsClient(client);
    return () => {
      client.close();
    };
  }, [handleMessage]);

  const sendMessage = useCallback(
    (type, payload = {}) => {
      if (!wsClient) return;
      wsClient.send(type, payload);
    },
    [wsClient]
  );

  const handleJoin = useCallback(
    (name) => {
      if (!name) return;
      setPlayerName(name);
      localStorage.setItem(STORAGE_NAME, name);
      sendMessage("join", { name, playerId: playerId || undefined });
    },
    [sendMessage, playerId]
  );

  const handleSetSecret = useCallback(
    (secret) => {
      if (!secret) return;
      sendMessage("host.set_secret", { secret });
    },
    [sendMessage]
  );

  const handleSubmitWord = useCallback(
    (word) => {
      if (!word) return;
      sendMessage("submit.word", { word });
    },
    [sendMessage]
  );

  const handleSendChat = useCallback(
    (message) => {
      if (!message) return;
      sendMessage("chat.say", { message });
    },
    [sendMessage]
  );

  const handleRequestStats = useCallback(() => {
    sendMessage("stats.request");
    setStatsVisible(true);
  }, [sendMessage]);

  const myResult = useMemo(() => {
    const rounds = Object.keys(personalResults).map(Number);
    if (!rounds.length) return null;
    const latest = Math.max(...rounds);
    return personalResults[latest];
  }, [personalResults]);

  const summaryEntries = useMemo(() => {
    if (!roomState) return [];
    const entries = roundSummaries[roomState.round];
    return entries || [];
  }, [roundSummaries, roomState]);

  const you = useMemo(() => {
    if (!roomState) return null;
    return roomState.players?.find((p) => p.id === playerId) || null;
  }, [roomState, playerId]);

  const isMyTurn = useMemo(() => currentTurn === playerId, [currentTurn, playerId]);
  const canSubmit = phase === "collecting" && isMyTurn;
  const canSetSecret = isHost && ["lobby", "next"].includes(phase);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>에저회전</h1>
          <p className="tagline">Azure Kaisen · アジュール回戦</p>
        </div>
        <div className="header-meta">
          <Timer phase={phase} round={roomState?.round || 0} timerMs={timerMs} connectionStatus={connectionStatus} />
          <div className="turn-indicator">
            {phase === "collecting" && currentTurn ? (
              <span className={isMyTurn ? "badge badge-active" : "badge"}>
                현재 턴: {roomState?.players?.find((p) => p.id === currentTurn)?.name || "?"}
              </span>
            ) : (
              <span className="badge">대기 중</span>
            )}
          </div>
          <a className="pdf-link" href="/docs/5일차.pdf" target="_blank" rel="noreferrer">
            강의자료 보기
          </a>
        </div>
      </header>

      <main className="app-main">
        <section className="panel chat-panel">
          <Chat
            messages={chatMessages}
            onSend={handleSendChat}
            disabled={connectionStatus !== "connected" || !playerId}
          />
        </section>

        <section className="panel game-panel">
          {!playerId && (
            <Lobby
              onJoin={handleJoin}
              initialName={playerName}
              connectionStatus={connectionStatus}
              lastError={lastError}
            />
          )}

          {playerId && canSetSecret && (
            <HostPanel onSubmit={handleSetSecret} pendingRound={pendingSecretRound} />
          )}

          {playerId && (
            <TurnPanel
              canSubmit={canSubmit}
              isMyTurn={isMyTurn}
              phase={phase}
              onSubmit={handleSubmitWord}
              lastError={lastError}
            />
          )}

          {playerId && (
            <section className="hint-card" aria-live="polite">
              <h2>개인 힌트</h2>
              {myResult ? (
                <div>
                  <p className="hint-text">{myResult.hint}</p>
                  <div className="hint-meta">
                    <span>라운드 {myResult.round}</span>
                    <span>점수 {myResult.score}</span>
                    {myResult.flags?.length ? <span>플래그: {myResult.flags.join(", ")}</span> : null}
                  </div>
                </div>
              ) : (
                <p className="hint-text muted">라운드 종료 후 힌트가 제공됩니다.</p>
              )}
            </section>
          )}

          {summaryEntries.length > 0 && (
            <section className="summary-card">
              <h2>라운드 요약</h2>
              <ul>
                {summaryEntries.map((entry) => (
                  <li key={entry.slot}>
                    <span className="summary-word">{entry.word}</span>
                    <span className="summary-score">{entry.score}점</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {playerId && (
            <button className="stats-button" onClick={handleRequestStats} disabled={phase === "lobby"}>
              통계 보기
            </button>
          )}
        </section>

        <aside className="panel score-panel">
          <Scoreboard roomState={roomState} youId={playerId} />
        </aside>
      </main>

      {winner && <WinnerBanner winner={winner} />}

      {statsVisible && stats && (
        <StatsModal stats={stats} onClose={() => setStatsVisible(false)} />
      )}
    </div>
  );
}
