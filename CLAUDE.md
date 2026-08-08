# CLAUDE.md

이 파일은 Claude Code가 `clipboard055` 프로젝트에서 작업할 때 따라야 할 지침이다.
새 세션에서 작업을 시작하기 전에 반드시 이 파일을 먼저 읽는다.

## 프로젝트 개요

**clipboard055**는 정의당 경남도당 간부들을 위한 일일 뉴스 브리핑 자동화 시스템이다.
매일 아침 7시, RSS 피드에서 노동·기후·여성·청년·복지·지역정치·정의당·연대당 뉴스를 수집하여 AI로 필터링·요약하고 텔레그램과 이메일로 발송한다.

- **전체 기획**: `PRD.md` 또는 `docs/PRD.md` 참조 (반드시 작업 전 확인)
- **개발자**: 레고 (비개발자, Claude Code로 개발 주도)
- **현재 단계**: Phase 1 (MVP — 핵심 5개 섹션)

## 기술 스택

- **언어**: Python 3.11
- **패키지 관리**: uv (선호) 또는 poetry
- **AI**: 2단계 구조 (싼 모델로 거르고, 좋은 모델로 요약)
  - **GPT-5.6 Luna** (OpenAI) — 1차 분류 (카테고리·중요도·스코프) — 2026-08-08 Haiku에서 교체
  - **Sonnet 4.6** (Anthropic) — 2차 요약·코멘트 생성 (필터링 통과 기사만)
- **저장소**: SQLite
- **발송**: python-telegram-bot, Resend (이메일)
- **스케줄링**: GitHub Actions cron
- **RSS**: feedparser

## 핵심 규칙 (반드시 지킬 것)

### 1. 언어
- **모든 주석과 docstring은 한국어로** 작성한다
- 변수·함수·클래스명은 영어로 (표준 관례)
- 커밋 메시지는 한국어로 (Conventional Commits 형식: `feat: RSS 수집 모듈 추가`)
- 로그 메시지는 한국어

### 2. 저작권 준수 (중요)
- RSS에서 가져온 기사 원문을 **그대로 복사·저장하지 않는다**
- AI 요약만 생성하고, **원문 링크를 반드시 포함**한다
- 스크래핑 시 `robots.txt`를 확인하고 준수한다

### 3. 비용 관리 (중요)
- Haiku와 Sonnet 호출 시 **토큰 사용량을 반드시 로그로 남긴다**
- `briefings` 테이블의 `haiku_tokens_in/out`, `sonnet_tokens_in/out`, `estimated_cost_usd`에 기록
- 일일 비용이 $1.5 초과하면 경고 로그 출력
- 월 비용이 $30 초과 예상 시: Sonnet 요약 기준을 중요도 4점 이상으로 자동 상향

### 4. 보안
- API 키·토큰은 **절대 코드에 하드코딩하지 않는다**
- 모든 비밀값은 환경변수(`.env` 파일) 또는 GitHub Secrets로 관리
- `.env`, `state/seen.db`, `logs/` 폴더는 `.gitignore`에 포함
- `recipients.yaml`은 예시 파일(`recipients.yaml.example`)만 공개, 실제 파일은 gitignore

### 5. 오류 처리
- RSS 피드 하나가 실패해도 **전체 파이프라인은 계속 실행**한다 (graceful degradation)
- Claude API 호출 실패 시: 1회 재시도, 2회 실패 시 해당 기사만 스킵하고 로그에 기록
- 텔레그램·이메일 발송 실패 시: 본인(레고)에게만 텔레그램 DM으로 오류 알림

### 6. 중립성·편향 방지
- AI에게 "중립적으로" 요약하도록 프롬프트에 명시
- **자당(정의당)을 과대평가하지 않기**: 단순 보도자료를 무조건 중요도 5점 주지 않도록 프롬프트에 명시
- **연대당(노동당·녹색당)을 과소평가하지 않기**: 수집 기사가 적을 수 있으므로 오히려 포함되기 쉽게 조정
- 9개 섹션 중 특정 섹션에만 기사가 몰리지 않도록 RSS 피드 분산 구성

## 프로젝트 구조

```
clipboard055/
├── .github/workflows/     # GitHub Actions
├── src/                   # 소스 코드
│   ├── main.py           # 파이프라인 오케스트레이션
│   ├── collect.py        # RSS 수집
│   ├── dedupe.py         # 중복 제거
│   ├── classify.py       # Haiku 분류 (9 카테고리)
│   ├── summarize.py      # Sonnet 요약
│   ├── section_builder.py # 9개 섹션 구성
│   ├── telegram_push.py  # 텔레그램 발송
│   ├── email_send.py     # 이메일 발송
│   ├── storage.py        # SQLite 관리
│   └── prompts/          # AI 프롬프트 텍스트 파일
│       ├── classify.txt
│       └── summarize.txt
├── config/               # 설정 파일 (YAML)
│   ├── feeds.yaml        # RSS 피드 목록
│   ├── keywords.yaml     # 필터링 키워드
│   └── recipients.yaml   # 이메일 수신자 (gitignore)
├── templates/            # Jinja2 템플릿
├── state/                # SQLite (gitignore)
├── logs/                 # 실행 로그 (gitignore)
├── tests/                # pytest 테스트
├── PRD.md                # 전체 기획서
└── CLAUDE.md             # 이 파일
```

## 카테고리 및 섹션 매핑 (9섹션)

| # | 섹션 | 이모지 | 카테고리 | 스코프 |
|---|------|--------|---------|--------|
| 1 | 노동·파업·산재 | 💼 | `labor` | 전국+지역 |
| 2 | 기후·환경 | 🌱 | `climate` | 전국+지역 |
| 3 | 여성·소수자 | ⚧ | `gender_minority` | 전국+지역 |
| 4 | 청년·청소년 | 🎓 | `youth` | 전국+지역 |
| 5 | 복지·돌봄 | 🤝 | `welfare_care` | 전국+지역 |
| 6 | 경남 지역 정치·선거 | 🗳 | `regional_politics` | 경남만 |
| 7 | **정의당 — 경남** | 🟡 | `justice_party` + `gyeongnam`/`both` | 경남 |
| 8 | **정의당 — 전국** | 🟨 | `justice_party` + `national` | 전국 |
| 9 | **노동당·녹색당 동향** | 🤝🌿 | `allied_parties` | 전국+지역 |

**카테고리 분류 우선순위**:
1. 정당명이 기사 핵심이면 정당 카테고리 우선 (예: "정의당, 노동 개혁안 발표" → `justice_party`, not `labor`)
2. 정책 분석이 중심이고 정당은 부차적이면 주제 카테고리
3. 3당 공동 성명: 정의당 주도면 `justice_party`, 노동당·녹색당 주도면 `allied_parties`

## 개발 원칙

### 단계별 개발
- **PRD의 Phase 순서를 따른다**. Phase 0 → 1 → 2 → 3 → 4
- Phase를 건너뛰지 않는다. 현재 Phase가 완료되지 않으면 다음 Phase로 넘어가지 않는다
- **Phase 1은 먼저 5개 섹션만 활성화** (노동·기후·경남정치·정의당경남·정의당전국). 나머지(여성·청년·복지·연대당)는 Phase 2

### 코드 품질
- 함수는 **하나의 책임만** 가진다 (단일 책임 원칙)
- 타입 힌트를 적극 사용한다 (`def classify(article: Article) -> Classification:`)
- 상수는 `UPPER_SNAKE_CASE`, 모듈 상단에 정의
- 매직 넘버 금지 (예: `4` 대신 `IMPORTANCE_THRESHOLD_SONNET = 3`)

### 테스트
- Phase 1 완료 시점까지 각 모듈의 **단위 테스트 1개 이상**
- Claude API 호출은 모킹(mocking)하여 테스트 — 실제 호출 금지
- 테스트 데이터는 `tests/fixtures/`에 샘플 RSS XML 파일로 저장

### 의존성 최소화
- 새 라이브러리 추가 전 **정말 필요한지 다시 생각**한다
- 표준 라이브러리로 해결 가능하면 그걸 우선 사용

## AI 프롬프트 규칙

### Haiku 분류 프롬프트
- `src/prompts/classify.txt`에 별도 파일로 저장
- 응답은 **반드시 JSON만** 요청
- 응답 파싱 실패 시: 해당 기사는 `category="other", importance=1`로 처리하고 로그
- **9개 카테고리 구분 규칙을 프롬프트에 명확히 포함** (특히 `justice_party` vs `allied_parties`)

### Sonnet 요약 프롬프트
- `src/prompts/summarize.txt`에 별도 파일로 저장
- `summary` 3-4문장, `comment` 1-2문장
- "추측 금지, 확실한 관점만" 규칙 포함
- 카테고리별 코멘트 방향 명시 (예: `justice_party`는 "도당 실무 영향", `allied_parties`는 "3당 연대 시사점")
- 응답 실패 시: 해당 기사는 요약 없이 제목·링크만 발송

## 커밋 규칙

Conventional Commits 형식 한국어 버전:
```
feat: RSS 수집 모듈 구현
fix: 중복 제거 시 한글 제목 비교 오류 수정
docs: README에 환경변수 설정 가이드 추가
refactor: classify.py 프롬프트 로딩 로직 분리
test: dedupe 모듈 단위 테스트 추가
chore: GitHub Actions 워크플로우 업데이트
```

**브랜치 전략**: 혼자 개발하므로 `main` 브랜치에 직접 커밋. 단, Phase 전환 시 태그 생성 (`v0.1-phase1-mvp` 등)

## 환경변수

`.env.example`에 다음 항목을 정의하고, 실제 값은 `.env`에 저장 (gitignore):

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=-100...        # 발송 대상 비공개 채널
TELEGRAM_ADMIN_USER_ID=...         # 오류 알림용 본인 ID

# Email (Resend)
RESEND_API_KEY=re_...
EMAIL_FROM_ADDRESS=briefing@...    # 발신자 이메일

# 기타
LOG_LEVEL=INFO
TIMEZONE=Asia/Seoul
```

## 작업 시작 전 체크리스트

Claude Code가 새 작업을 시작할 때:

1. [ ] `PRD.md` 읽어서 현재 Phase와 할 일 확인
2. [ ] 이 `CLAUDE.md` 재확인 (규칙 준수)
3. [ ] `pyproject.toml` 확인하여 현재 의존성 파악
4. [ ] 마지막 커밋 로그(`git log -5`) 확인하여 진행 상황 파악
5. [ ] 작업 완료 후 반드시 커밋 (의미 단위로 작게 나눠서)

## 레고의 작업 선호

- **점진적 개발**: 한 번에 완벽하게 만들기보다 작게 쪼개서 반복
- **실제 동작 우선**: 이론적으로 좋은 것보다 지금 돌아가는 것
- **설정 기반**: 코드 수정 없이 YAML만 바꿔서 운영 변경 가능하게
- **한국어 친화**: 에러 메시지·로그도 한국어로 읽기 쉽게
- **문서화**: 각 모듈 상단에 해당 모듈이 무엇을 하는지 한국어로 주석

## 주의사항

- **비개발자**와 작업 중이다. 전문 용어는 풀어서 설명하거나 간단한 주석을 달아준다
- 코드가 복잡해지면 레고에게 **왜 이렇게 설계했는지 한국어로 설명**한다
- 레고는 **레고 자신이 이해할 수 있는 코드**를 원한다. 화려한 추상화보다 직관적인 구조 선호

## 문서 지도 (읽는 순서)

1. `CLAUDE.md` (이 파일) — 개발 규칙. 매 세션 자동으로 읽힘
2. `PRD.md` — 무엇을 만드는가, 현재 상태, 로드맵 (2026-08-08 재작성)
3. `docs/todolist.md` — 다음에 할 일 (항목마다 왜/어느 파일/어떤 방향)
4. `docs/superpowers/specs/` — 과거 설계 메모 (참고용)

- 작업 일지는 별도 파일 없이 **커밋 로그**로 관리한다.
- 문서 갈래 나누는 기준은 전역 규칙(`~/dotfiles/doc-conventions.md`) 참조.

---

**문서 버전**: v1.1 (2026-04-17)
**변경 이력**:
- v1.0: 초기 버전 (8섹션 구조)
- v1.1: 9섹션 구조 반영 — 정의당 경남/전국 분리, 노동당·녹색당 통합 섹션 신설, 카테고리 분류 우선순위 규칙 추가
- v1.2 (2026-08-08): 관련 문서 절을 문서 지도로 교체 — 존재하지 않는 README.md·docs/feeds.md 참조 제거, PRD.md·todolist.md 연결

**관리**: 레고 + Claude
