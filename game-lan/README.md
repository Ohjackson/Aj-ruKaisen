# 에저회전 (Azure Kaisen, アジュール回戦)

에저회전은 해커톤·수업에서 “로컬 PDF 기반 AI 힌트 + 실시간 WebSocket 게임”을 빠르게 테스트하기 위한 LAN 전용 추리 게임입니다. 방장은 매 라운드 비밀 제시어를 입력하고, 플레이어들은 턴마다 단어를 제출해 PDF에서 추출한 간접 힌트를 받으며 점수를 겨룹니다. 정답은 게임 중·종료 후에도 절대 공개되지 않습니다.

---

## ✨ 핵심 특징
- **3라운드 단일 룸**: 2~5명이 동시에 플레이하며 고정 3라운드를 진행합니다.
- **PDF 기반 AI 힌트**: FastAPI 서버가 `backend/docs/5일차.pdf`를 인덱싱해 외부 LLM 없이 힌트를 생성합니다.
- **턴제 & 타이머**: 서버 권위 30초 타이머(`TURN_TIMER_SECONDS` 환경변수 변경 가능)와 순차 턴 진행.
- **정답 비공개 원칙**: 어떤 이벤트에도 제시어가 노출되지 않으며 힌트는 유니캐스트로 제공됩니다.
- **종료 후 통계**: 플레이어 × 라운드 테이블(단어/점수)과 총점/순위, 승자 배지 렌더링.

---

## 📁 폴더 구조
```
/game-lan
  ├─ backend
  │   ├─ app.py             # FastAPI + WebSocket 엔드포인트
  │   ├─ state.py           # FSM, 인메모리 상태/점수 로직
  │   ├─ requirements.txt
  │   └─ ai/
  │        ├─ pdf_engine.py # PDF 추출 및 힌트 생성
  │        └─ rules.json    # 금칙어·스포일러 규칙
  │   └─ docs/5일차.pdf     # 강의자료 (정적 서빙)
  ├─ frontend
  │   ├─ index.html
  │   ├─ package.json / vite.config.js
  │   └─ src/
  │        ├─ App.jsx, main.jsx, styles.css
  │        ├─ components/   # UI 컴포넌트 (Lobby, HostPanel, TurnPanel 등)
  │        └─ lib/ws.js     # 자동 재연결 WebSocket 헬퍼
  ├─ .env.example
  └─ README.md
```

---

## 🔧 환경 요구사항
- **Python 3.10+**
- **Node.js 18+** (npm 포함)
- LAN 접속을 위해 8000/5173 포트 방화벽 허용

`cp .env.example .env`로 기본 환경값을 복사해 사용할 수 있습니다.

- `VITE_API_BASE` : 프론트에서 REST·정적 리소스를 호출할 백엔드 Origin (기본 `http://<호스트>:8000`)
- `VITE_WS_PATH` / `VITE_WS_URL` : WebSocket 경로 또는 전체 URL (기본 `/ws` → `ws://<호스트>:8000/ws`)
- `TURN_TIMER_SECONDS` : 서버 턴 타이머 기본값(초)

---

## 🚀 실행 가이드

### 1) 백엔드 (FastAPI)
```bash
cd game-lan/backend
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```
- 서버 기동 시 로그에 `http://<LAN_IP>:8000` 과 예상 프론트 URL(`:5173`)이 출력됩니다.
- 주요 엔드포인트
  - `GET /health` → `{ "status": "ok" }`
- `GET /config` → `{ rounds: 3, turnSeconds: 30 }`
- `GET /docs/5일차.pdf` → 프론트에서 열람 가능한 강의자료
- `GET /db` → 인메모리 게임 상태 스냅샷(제시어 본문은 미노출)
- `WS /ws` → 게임용 JSON 이벤트 스트림

### 2) 프론트엔드 (React + Vite)
```bash
cd game-lan/frontend
npm install
npm run dev -- --host
```
- 로컬 접속: `http://localhost:5173`
- LAN 접속: `http://<서버 LAN IP>:5173` (백엔드 로그 참고)
- 빌드 & 프리뷰
  ```bash
  npm run build
  npm run preview -- --host
  ```

---

## 🧠 게임 플레이 흐름
1. **로비**: 닉네임으로 참가하면 첫 입장자가 자동 방장.
2. **라운드 시작(총 3회)**
   - 방장: 비밀 제시어 입력(서버 내 비공개 저장)
   - 턴제: 플레이어가 자신의 차례에 단어 1개 제출 (중복·금칙어 필터)
   - 서버 타이머(기본 30초) 또는 전원 제출 시 자동 종료
3. **라운드 종료 처리**
   - 각 플레이어에게 개인 힌트 유니캐스트 전송 (`round.result:me`)
   - 공개 채팅에는 익명 라운드 요약(`round.summary`)만 브로드캐스트
   - 점수 계산 후 스코어보드 갱신
4. **3라운드 반복** 후 최종 승자 배지(`end.winner`)와 통계 모달(`stats.open`) 표시

> **정답은 절대 공개되지 않습니다.** 힌트와 요약에도 제시어·동의어가 포함되지 않도록 PDF 엔진이 마스킹합니다.

---

## 🧮 점수 규칙
- **+1 기본점**: 유효 단어 제출 시
- **+1 희소성**: 라운드 내 유일한 단어인 경우
- **+1 비직접성**: AI 힌트 엔진이 `too_direct` 플래그를 주지 않은 경우
- **페널티 (0 또는 −1)**: 금칙어(`forbidden`), 직접 스포일러(`too_direct`), 노이즈(`off_topic`) 등 `rules.json` 기반
- AI의 `ai_score_suggestion`은 참고용이며 최종 점수는 서버가 확정합니다.

---

## 🔄 WebSocket 이벤트 요약
| 방향 | 타입 | 설명 |
| --- | --- | --- |
| 클라 → 서버 | `join`, `leave`, `host.set_secret`, `submit.word`, `chat.say`, `stats.request`, `ping` |
| 서버 → 클라 | `joined`, `room.state`, `turn.next`, `tick`, `round.started`, `round.result:me`, `round.summary`, `phase.changed`, `round.ready`, `end.winner`, `stats.open`, `chat.message`, `error`, `pong` |

- **개별 힌트** (`round.result:me`)는 항상 해당 플레이어에게만 전송.
- **라운드 요약**에는 플레이어 이름 대신 슬롯/단어/점수만 제공.

---

## ✅ QA 체크리스트
1. 3명 이상 접속 → 라운드 1 진행 → 각자 서로 다른 힌트 수신, 공개 채팅은 익명 요약만 출력
2. 금칙어/스포일러 제출 시 해당 플레이어 점수 페널티 및 힌트 톤 완화
3. 3라운드 종료 후 Winner 배지와 통계 모달에서 라운드별 단어/점수/총점/순위 확인 (정답 미노출)
4. 새로고침 후 로컬 스토리지에 저장된 `playerId`/닉네임으로 세션 복구
5. 동일 LAN 다른 기기에서 접속하여 실시간 동기화 확인

---

## 📌 개발 메모
- `TURN_TIMER_SECONDS` 환경변수로 기본 턴 시간을 조정할 수 있습니다.
- `backend/ai/rules.json`에 금칙어·스포일러 목록을 추가하면 힌트 및 채팅 마스킹에 즉시 반영됩니다.
- `pdf_engine.py`의 `refresh()` 메서드를 이용하면 서버 재시작 없이 PDF/룰 갱신을 적용할 수 있습니다.

---

## 🖼️ 스크린샷
> 실행 후 캡처 이미지를 이 섹션에 추가하세요.

---

### 라이선스 안내
- `backend/docs/5일차.pdf`는 교육용 예시 자료로 포함되어 있으며, 원 저작권자의 정책을 준수해야 합니다.
- 기타 소스 코드는 별도 명시가 없는 한 프로젝트 참가자가 자유롭게 수정·확장할 수 있습니다.
