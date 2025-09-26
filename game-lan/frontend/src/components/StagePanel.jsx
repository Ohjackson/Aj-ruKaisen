import { useMemo, useState } from "react";

const phaseLabels = {
  lobby: "대기실",
  ready: "준비",
  submission: "밤의 의식",
  resolution: "AI 판정",
  discussion: "낮의 토론",
  transition: "황혼",
  end: "게임 종료",
};

function formatMs(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export default function StagePanel({
  phase,
  round,
  timerMs,
  canSubmit,
  onSubmit,
  summary = [],
  discussionPrompt,
  prepInfo,
  isHost,
  hasJoined,
}) {
  const [word, setWord] = useState("");

  const phaseLabel = phaseLabels[phase] || phase;
  const headerText = useMemo(() => {
    switch (phase) {
      case "lobby":
        return "플레이어를 기다리는 중";
      case "ready":
        return "모든 플레이어의 READY가 필요합니다";
      case "submission":
        return "밤이 찾아왔습니다. 단어를 속삭이세요.";
      case "resolution":
        return "AI가 힌트를 준비하고 있습니다.";
      case "discussion":
        return "낮이 밝았습니다. 힌트를 공유하고 토론하세요.";
      case "transition":
        return "황혼이 내려앉습니다. 곧 새로운 밤이 시작됩니다.";
      case "end":
        return "Azure 의식이 마무리되었습니다.";
      default:
        return "Azure 흐름";
    }
  }, [phase]);

  const showStartButton = phase === "ready" && isHost;

  return (
    <section className="stage-panel">
      <header className="stage-header">
        <div>
          <span className="phase-label">{phaseLabel}</span>
          <span className="round-badge">Round {round}</span>
        </div>
        <div className="stage-timer">{formatMs(timerMs)}</div>
      </header>

      {prepInfo && phase === "submission" ? (
        <div className="prep-banner">
          <span className="prep-theme">테마: {prepInfo.theme}</span>
          {prepInfo.source === "azure" ? <span className="badge azure">Azure AI</span> : <span className="badge fallback">Fallback</span>}
          {prepInfo.rationale ? <p className="prep-rationale">{prepInfo.rationale}</p> : null}
        </div>
      ) : null}

      <div className="stage-body">
        <h2>{headerText}</h2>

        {phase === "lobby" && (
          <p>닉네임을 입력하고 READY를 눌러주세요.</p>
        )}

        {phase === "ready" && (
          <div className="start-block">
            <p>모든 플레이어가 READY 상태가 되면 방장의 시작 버튼이 활성화됩니다.</p>
            {showStartButton ? <p className="muted">컨트롤 패널에서 게임을 시작하세요.</p> : null}
          </div>
        )}

        {phase === "submission" && (
          <form
            className="word-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!word.trim()) return;
              onSubmit(word.trim());
              setWord("");
            }}
          >
            <label htmlFor="word-input">이번 밤에 속삭일 단어</label>
            <input
              id="word-input"
              value={word}
              onChange={(event) => setWord(event.target.value)}
              placeholder="한 단어 입력"
              disabled={!canSubmit}
              autoComplete="off"
            />
            <button type="submit" disabled={!canSubmit || !word.trim()}>
              제출
            </button>
            {!canSubmit && <p className="muted">제출 가능 시간이 아닙니다.</p>}
          </form>
        )}

        {phase === "discussion" && (
          <div className="discussion-block">
            {discussionPrompt ? <p className="prompt">{discussionPrompt}</p> : null}
            <ul className="summary-feed">
              {summary.map((entry, idx) => (
                <li key={idx}>
                  <span className="summary-name">{entry.name || entry.playerId}</span>
                  <span className="summary-word">{entry.word}</span>
                  <span className="summary-score">{entry.score}점</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {phase === "resolution" && <p>Azure AI가 힌트를 전송할 때까지 잠시만 기다려주세요.</p>}
        {phase === "transition" && <p>밤과 낮이 교차합니다. 잠시 후 다음 라운드가 시작됩니다.</p>}
        {phase === "end" && hasJoined && <p>다시 플레이하려면 READY를 누르고 방장의 시작을 기다리세요.</p>}
      </div>
    </section>
  );
}
