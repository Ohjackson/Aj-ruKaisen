# 에저회전 (Azure Kaisen, アジュール回戦)

에저회전은 Azure OpenAI와 로컬 PDF를 결합해 **AI가 전 과정을 진행**하는 LAN 추리 게임입니다. 플레이어는 닉네임으로 입장해 READY를 누르고, 방장이 시작 버튼을 누르면 Azure AI가 제시어를 고르고 점수/힌트까지 판정합니다. 모든 힌트와 판정은 서버 내부에서만 처리되어 정답 텍스트는 절대 공개되지 않습니다.

---

## ✨ 핵심 특징
- **AI 주도 라운드**: READY → 방장 시작 → Azure AI가 PDF(`backend/docs/5일차.pdf`)에서 제시어 선택 → 밤(단어 제출) → AI 판정 → 낮(토론) → 황혼(전환) 3회 반복.
- **Azure OpenAI + 로컬 PDF**: 강의 자료를 컨텍스트로 전달해 제시어·힌트를 뽑아내고, 실패 시 로컬 PDF 엔진이 자동으로 폴백합니다.
- **다이내믹 UI**: 밤/낮/황혼 테마가 바뀌며 중앙에는 단계별 안내, 하단에는 토론 시간에만 열리는 채팅 패널이 표시됩니다.
- **자동 점수/통계**: Azure가 내려준 JSON을 기준으로 점수·플래그·요약을 계산하고, 종료 후 Winner 배지와 라운드별 통계 모달을 제공합니다.
- **LAN 친화 설계**: FastAPI WebSocket + React(Vite) 구조, 인증/외부 서비스 최소화. 동일 네트워크에서 여러 기기가 바로 접속 가능.

---

## 📁 폴더 구조
```
/game-lan
  ├─ backend
  │   ├─ app.py             # FastAPI WebSocket 서버 & Azure orchestration
  │   ├─ state.py           # 플레이어/라운드 상태, READY/FSM 관리
  │   ├─ requirements.txt
  │   └─ ai/
  │        ├─ azure_agent.py # Azure OpenAI 호출 + PDF 폴백 로직
  │        ├─ pdf_engine.py  # 로컬 PDF 힌트 생성기
  │        └─ rules.json     # 금칙어·스포일러 규칙
  │   └─ docs/5일차.pdf     # 강의자료 (정적 제공)
  ├─ frontend
  │   ├─ index.html
  │   ├─ package.json / vite.config.js
  │   └─ src/
  │        ├─ App.jsx, main.jsx, styles.css
  │        ├─ components/   # PlayerBoard, StagePanel, HintModal, Chat 등
  │        └─ lib/ws.js     # 자동 재연결 WebSocket 헬퍼
  ├─ .env.example
  └─ README.md
```

---

## 🔧 환경 요구사항 & 설정
- **Python 3.10+**, **Node.js 18+ (npm)**
- LAN에서 8000(FastAPI) / 5173(Vite) 포트를 허용하세요.
- `.env.example`을 복사해 필요한 값을 채웁니다.

### 주요 환경 변수
- `VITE_API_BASE`, `VITE_WS_PATH`(또는 `VITE_WS_URL`): 프론트 → 백엔드 라우팅 설정.
- `AI_PDF_PATH`, `AI_RULES_PATH`: Azure와 폴백 엔진이 참조할 로컬 자원 경로.
- `AI_HINTS_ENABLED`: `0`/`false`로 두면 Azure 판정 없이 폴백 엔진만 사용.
- `MAX_ROUNDS`, `SUBMISSION_SECONDS`, `DISCUSSION_SECONDS`, `TRANSITION_SECONDS`: 라운드 수와 밤/낮/전환 타이머 설정.
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`: Azure OpenAI Chat Completions 엔드포인트 설정.

> Azure 설정이 비어 있으면 자동으로 PDF 폴백 로직이 동작합니다.

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
- 기동 시 로그로 `http://<LAN_IP>:8000` 과 프론트 예상 주소(`:5173`)가 출력됩니다.
- 주요 엔드포인트
  - `GET /health` → 헬스 체크
  - `GET /config` → 라운드/타이머 설정 값
  - `GET /docs/5일차.pdf` → 강의자료 다운로드
  - `GET /db` → 인메모리 상태 스냅샷(제시어 본문은 미노출)
  - `WS /ws` → 게임 이벤트 스트림

### 2) 프론트엔드 (React + Vite)
```bash
cd game-lan/frontend
npm install
npm run dev -- --host
```
- 접속 URL: `http://localhost:5173` 또는 `http://<LAN_IP>:5173`
- 프로덕션 빌드/미리보기
  ```bash
  npm run build
  npm run preview -- --host
  ```

---

## 🧠 게임 흐름 (Azure 단계)
1. **대기 & READY**: 플레이어가 닉네임으로 입장하고 READY 토글. 방장은 첫 입장자.
2. **방장 시작**: 모든 플레이어가 READY면 방장이 “시작”을 눌러 게임 리셋 → Azure가 PDF 컨텍스트로 제시어 선택.
3. **밤 (submission)**: 제한 시간(`SUBMISSION_SECONDS`) 동안 각 플레이어가 단어 1개 제출. 채팅은 비활성.
4. **AI 판정 (resolution)**: Azure OpenAI가 제출 요약/점수/힌트를 JSON으로 반환. 실패 시 PDF 폴백.
5. **밤 힌트 팝업**: 각 플레이어에게 개인 힌트 모달(`round.result:me`)이 표시됩니다.
6. **낮 (discussion)**: 타이머(`DISCUSSION_SECONDS`) 동안 채팅이 열리고 요약(`round.summary`)과 토론 프롬프트가 노출됩니다.
7. **황혼 (transition)**: 짧은 전환(`TRANSITION_SECONDS`) 후 다음 라운드로 이동. 라운드 3회 종료 시 Winner + 통계(`stats.open`).

> 정답 문자열은 어떠한 이벤트/로그에도 노출되지 않으며, 힌트·요약·통계에 포함되지 않습니다.

---

## 🧮 점수 & 힌트 로직
- Azure 응답 JSON의 `score`/`flags`/`hint`를 서버가 그대로 반영합니다.
- Azure 호출 실패 시 폴백 PDF 엔진이 **기본점 + 희소성 + 비직접성** 규칙으로 점수를 계산하고 힌트를 생성합니다.
- 모든 점수 변경 결과는 `room.state`와 `round.summary`를 통해 브로드캐스트됩니다.

---

## 🔄 WebSocket 이벤트 요약
| 방향 | 타입 | 설명 |
| --- | --- | --- |
| 클라 → 서버 | `join`, `leave`, `player.ready_toggle`, `host.start_game`, `submit.word`, `chat.say`, `stats.request`, `ping` |
| 서버 → 클라 | `joined`, `room.state`, `phase.changed`, `round.prep`, `tick`, `round.result:me`, `round.summary`, `end.winner`, `stats.open`, `chat.message`, `player.ready`, `error`, `pong` |

---

## ✅ QA 체크리스트
1. 전원이 READY 후 방장이 시작 → Azure가 제시어를 고르고 밤 단계로 진입.
2. 밤에 각자 단어 제출 → 힌트 모달이 개인별로 표시, 채팅은 비활성.
3. 낮 타이머 동안 채팅이 열리고 요약/프롬프트 확인 가능.
4. Azure 오류 시에도 폴백 엔진이 점수/힌트를 제공해 라운드가 정상 진행.
5. 3라운드 종료 후 Winner 배지 + 통계 모달에 단어/점수/힌트가 정확히 기재 (정답 비공개 유지).
6. 새 게임을 위해 READY를 다시 눌러도 상태가 정상적으로 초기화.

---

## 🖼️ 스크린샷
> 실제 실행 화면을 추가해 주세요 (밤/낮 테마, 힌트 모달, Winner 등).

---

### 라이선스 & 주의
- `backend/docs/5일차.pdf`는 교육용 예제로 포함되어 있으며 원저작권자의 정책을 따릅니다.
- Azure OpenAI 호출 시 사용량/비용을 확인하세요. 키가 없으면 폴백 엔진으로 자동 전환됩니다.
