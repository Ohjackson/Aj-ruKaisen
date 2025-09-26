# 에저회전 (Azure Kaisen)

Azure Kaisen은 3라운드 동안 방장이 숨긴 제시어를 추리하는 LAN 실습용 실시간 게임입니다. 플레이어는 턴마다 단어를 하나씩 제출하고, 서버는 로컬 PDF(`backend/docs/5일차.pdf`)에서 추출한 정보로 AI 힌트를 제공합니다. 정답은 게임 진행 중과 종료 후에도 절대 공개되지 않습니다.

## 주요 기능

- 단일 룸(2~5명) × 3라운드 고정 진행
- 방장 제시어 입력 → 턴제 단어 제출 → AI 개인 힌트/점수 부여 → 라운드 요약 → 최종 우승자 표시
- FastAPI WebSocket 기반 서버 권위 타이머(기본 30초)
- PDF 기반 AI 힌트 엔진 (외부 LLM/네트워크 미사용)
- React + Vite 프론트엔드, 자동 재연결 WebSocket 헬퍼 포함
- 게임 종료 후 “통계 보기” 모달에서 라운드별 단어/점수/총점/순위 확인

## 폴더 구조

```
/game-lan
  /backend
    app.py
    state.py
    /ai
      pdf_engine.py
      rules.json
    /docs
      5일차.pdf
    requirements.txt
  /frontend
    index.html
    package.json
    vite.config.js
    /src
      App.jsx
      main.jsx
      styles.css
      /components
        Chat.jsx
        HostPanel.jsx
        Lobby.jsx
        Scoreboard.jsx
        StatsModal.jsx
        Timer.jsx
        TurnPanel.jsx
        WinnerBanner.jsx
      /lib
        ws.js
  .env.example
  README.md
```

## 실행 전 준비

- **Python 3.10+**
- **Node.js 18+** (npm 포함)
- 동일 네트워크(LAN)에서 접속하려면 방화벽에서 8000/5173 포트를 허용하세요.

`.env.example`을 복사해 필요한 값을 조정할 수 있습니다.

```
cp .env.example .env
```

<br>

## 백엔드 실행 (FastAPI / uvicorn)

```bash
cd game-lan/backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

서버 기동 시 콘솔에 `http://<LAN_IP>:8000` 과 예상 프론트 URL(`:5173`)이 출력됩니다.

### 주요 HTTP/WS 엔드포인트

- `GET /health` → `{ "status": "ok" }`
- `GET /config` → 라운드/타이머 설정
- `GET /docs/5일차.pdf` → 강의자료 PDF 다운로드
- `WS /ws` → 게임 이벤트 (JSON 기반)

## 프론트엔드 실행 (React / Vite)

```bash
cd game-lan/frontend
npm install
npm run dev -- --host
```

- 기본 주소: `http://localhost:5173`
- LAN 접속: `http://<서버 LAN IP>:5173` (백엔드 로그 참고)
- Vite 개발 서버는 동일 LAN의 다른 기기에서 바로 접속 가능합니다.

### 빌드 & 미리보기

```bash
npm run build
npm run preview -- --host
```

## WebSocket 이벤트 개요

| 방향 | 타입 | 설명 |
| --- | --- | --- |
| 클라→서버 | `join`, `leave`, `host.set_secret`, `submit.word`, `chat.say`, `stats.request`, `ping` |
| 서버→클라 | `joined`, `room.state`, `turn.next`, `tick`, `round.result:me`, `round.summary`, `round.started`, `round.ready`, `phase.changed`, `end.winner`, `stats.open`, `chat.message`, `error`, `pong` |

개별 힌트(`round.result:me`)는 항상 유니캐스트로 전송되며 정답 문자열은 어떤 이벤트에도 포함되지 않습니다.

## 점수 규칙 요약

- 기본 +1: 유효 제출
- 희소성 +1: 해당 라운드에서 유일한 단어일 때
- 비직접성 +1: AI 엔진이 `too_direct` 플래그를 주지 않았을 때
- 페널티 (rules.json 기반): 금칙어/스포일러/오프토픽 시 0 또는 -1

## QA 시나리오

1. 3인 접속 → 방장 지정 → 라운드1 턴 제출 → 타이머 만료 → 각자 서로 다른 힌트 수신, 공개 채팅에는 익명 요약만 표시
2. 금칙어 또는 직접 스포일러 제출 시 해당 플레이어 점수 페널티 적용, 힌트 문구 완화
3. 3라운드 종료 후 Winner 배너와 함께 StatsModal에서 라운드별 단어/점수/총점/순위 확인 (정답 미노출)
4. 새로고침/재접속 시 저장된 `playerId`/닉네임으로 즉시 복구
5. 동일 LAN의 다른 기기에서 프론트 URL 접속 → WebSocket 자동 연결 및 실시간 진행 확인

## 스크린샷

> (환경 실행 후 캡처를 추가하세요.)

---

### 라이선스

이 저장소에 포함된 `5일차.pdf`는 강의자료 예시로만 제공되며, 사용 범위는 원 저작권자의 정책을 따릅니다.
