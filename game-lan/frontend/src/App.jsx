import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Chat from "./components/Chat.jsx";
import PlayerBoard from "./components/PlayerBoard.jsx";
import StagePanel from "./components/StagePanel.jsx";
import StatsModal from "./components/StatsModal.jsx";
import WinnerBanner from "./components/WinnerBanner.jsx";
import HintModal from "./components/HintModal.jsx";
import WSClient from "./lib/ws.js";

const STORAGE_ID = "akPlayerId";
const STORAGE_NAME = "akPlayerName";

const initialPlayerId = () => localStorage.getItem(STORAGE_ID) || "";
const initialPlayerName = () => localStorage.getItem(STORAGE_NAME) || "";

const phaseThemeMap = {
  lobby: "dawn",
  ready: "dawn",
  submission: "night",
  resolution: "void",
  discussion: "day",
  transition: "dusk",
  end: "starfall",
};

const themeTitle = {
  dawn: "Azure Dawn",
  night: "Azure Nightfall",
  day: "Azure Daybreak",
  dusk: "Azure Dusk",
  void: "Azure Sync",
  starfall: "Azure Epilogue",
};

const computeApiBase = () => {
  const override = import.meta.env.VITE_API_BASE;
  if (override) return override.replace(/\/$/, "");
  const { protocol, hostname } = window.location;
  const port = import.meta.env.VITE_API_PORT || "8000";
  return `${protocol}//${hostname}:${port}`;
};

const computeWsUrl = (apiBase) => {
  const override = import.meta.env.VITE_WS_URL;
  if (override) return override;
  const path = import.meta.env.VITE_WS_PATH || "/ws";
  const url = new URL(apiBase);
  const wsProtocol = url.protocol === "https:" ? "wss" : "ws";
  return `${wsProtocol}://${url.host}${path}`;
};

export default function App() {
  const [wsClient, setWsClient] = useState(null);
  const [connectionStatus, setConnectionStatus] = useState("connecting");
  const [playerId, setPlayerId] = useState(initialPlayerId);
  const [playerName, setPlayerName] = useState(initialPlayerName);
  const [isHost, setIsHost] = useState(false);
  const [phase, setPhase] = useState("lobby");
  const [round, setRound] = useState(0);
  const [timerMs, setTimerMs] = useState(0);
  const [players, setPlayers] = useState([]);
  const [roomState, setRoomState] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [prepInfo, setPrepInfo] = useState(null);
  const [discussionPrompt, setDiscussionPrompt] = useState("");
  const [roundSummaries, setRoundSummaries] = useState({});
  const [stats, setStats] = useState(null);
  const [statsVisible, setStatsVisible] = useState(false);
  const [winner, setWinner] = useState(null);
  const [hintQueue, setHintQueue] = useState([]);
  const [activeHint, setActiveHint] = useState(null);
  const [lastError, setLastError] = useState("");
  const apiBase = useMemo(() => computeApiBase(), []);
  const wsUrl = useMemo(() => computeWsUrl(apiBase), [apiBase]);
  const latestRoundRef = useRef(0);

  const enqueueHint = useCallback((payload) => {
    setHintQueue((prev) => [...prev, payload]);
  }, []);

  useEffect(() => {
    if (!activeHint && hintQueue.length) {
      setActiveHint(hintQueue[0]);
      setHintQueue((prev) => prev.slice(1));
    }
  }, [hintQueue, activeHint]);

  const handleMessage = useCallback((event) => {
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
        setRound(payload.round);
        setTimerMs(payload.timerMs || 0);
        setPlayers(payload.players || []);
        latestRoundRef.current = payload.round;
        break;
      }
      case "tick": {
        if (!payload.round || payload.round === latestRoundRef.current) {
          setTimerMs(payload.timerMs || 0);
        }
        break;
      }
      case "phase.changed": {
        setPhase(payload.phase);
        if (payload.round) {
          setRound(payload.round);
          latestRoundRef.current = payload.round;
        }
        if (payload.phase === "discussion") {
          setDiscussionPrompt(payload.prompt || "서로 힌트를 교환하며 비밀을 추적하세요.");
        }
        if (payload.phase === "submission") {
          setDiscussionPrompt("");
          setWinner(null);
          setStatsVisible(false);
        }
        break;
      }
      case "round.prep": {
        setPrepInfo(payload);
        break;
      }
      case "round.summary": {
        setRoundSummaries((prev) => ({ ...prev, [payload.round]: payload.entries || [] }));
        break;
      }
      case "round.result:me": {
        enqueueHint(payload);
        break;
      }
      case "chat.message": {
        setChatMessages((prev) => [...prev.slice(-99), payload]);
        break;
      }
      case "stats.open": {
        setStats(payload);
        break;
      }
      case "end.winner": {
        setWinner(payload);
        setStatsVisible(true);
        break;
      }
      case "player.ready": {
        setPlayers((prev) => prev.map((p) => (p.id === payload.playerId ? { ...p, ready: payload.ready } : p)));
        break;
      }
      case "error": {
        setLastError(payload.message || "문제가 발생했습니다.");
        break;
      }
      default:
        break;
    }
  }, [enqueueHint]);

  useEffect(() => {
    const client = new WSClient(wsUrl, {
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
  }, [wsUrl, handleMessage]);

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

  const handleReadyToggle = useCallback(() => {
    sendMessage("player.ready_toggle");
  }, [sendMessage]);

  const handleStartGame = useCallback(() => {
    sendMessage("host.start_game");
  }, [sendMessage]);

  const handleSubmitWord = useCallback(
    (word) => {
      sendMessage("submit.word", { word });
    },
    [sendMessage]
  );

  const handleSendChat = useCallback(
    (message) => {
      sendMessage("chat.say", { message });
    },
    [sendMessage]
  );

  const handleRequestStats = useCallback(() => {
    sendMessage("stats.request");
    setStatsVisible(true);
  }, [sendMessage]);

  const handleHintClose = useCallback(() => {
    setActiveHint(null);
  }, []);

  const allReady = useMemo(() => {
    if (!players.length) return false;
    return players.filter((p) => p.connected).every((player) => player.ready);
  }, [players]);

  const currentSummary = roundSummaries[round] || [];
  const phaseTheme = phaseThemeMap[phase] || "dawn";
  const themeLabel = themeTitle[phaseTheme] || "Azure";
  const canSubmit = phase === "submission";
  const canChat = ["discussion", "lobby", "ready"].includes(phase);
  const canToggleReady = ["lobby", "ready", "end"].includes(phase) && playerId;
  const showStartButton = phase === "ready" && isHost;
  const joined = Boolean(playerId);

  return (
    <div className={`app-shell theme-${phaseTheme}`}>
      <header className="top-bar">
        <div className="brand-block">
          <h1>에저회전</h1>
          <p className="tagline">{themeLabel}</p>
        </div>
        <div className="status-block">
          <span className={`connection ${connectionStatus}`}>{connectionStatus}</span>
          {lastError && <span className="error-pill">{lastError}</span>}
        </div>
        <div className="control-block">
          {!joined ? (
            <form
              className="join-form"
              onSubmit={(event) => {
                event.preventDefault();
                const formData = new FormData(event.currentTarget);
                const value = (formData.get("nickname") || "").toString().trim();
                if (!value) return;
                handleJoin(value);
                event.currentTarget.reset();
              }}
            >
              <input name="nickname" placeholder="닉네임" defaultValue={playerName} />
              <button type="submit" disabled={connectionStatus !== "connected"}>
                입장
              </button>
            </form>
          ) : (
            <div className="control-buttons">
              <button onClick={handleReadyToggle} disabled={!canToggleReady} className={roomState?.players?.find((p) => p.id === playerId)?.ready ? "primary" : ""}>
                READY
              </button>
              {showStartButton ? (
                <button className="primary" onClick={handleStartGame} disabled={!allReady}>
                  시작
                </button>
              ) : null}
              <button onClick={handleRequestStats}>
                통계
              </button>
              <a className="pdf-link" href={`${apiBase}/docs/5일차.pdf`} target="_blank" rel="noreferrer">
                강의자료
              </a>
            </div>
          )}
        </div>
      </header>

      <section className="player-strip">
        <PlayerBoard players={players} />
      </section>

      <main className="main-stage">
        <StagePanel
          phase={phase}
          round={round}
          timerMs={timerMs}
          canSubmit={canSubmit}
          onSubmit={handleSubmitWord}
          summary={currentSummary}
          discussionPrompt={discussionPrompt}
          prepInfo={prepInfo}
          isHost={isHost}
          hasJoined={joined}
        />

        <div className="chat-wrapper">
          <Chat
            messages={chatMessages}
            onSend={handleSendChat}
            disabled={!canChat || !joined}
            placeholder={canChat ? "메시지를 입력하세요" : "토론 시간이 아닙니다"}
          />
        </div>
      </main>

      {activeHint && <HintModal result={activeHint} onClose={handleHintClose} />}
      {winner && <WinnerBanner winner={winner} />}
      {statsVisible && stats && <StatsModal stats={stats} onClose={() => setStatsVisible(false)} />}
    </div>
  );
}
