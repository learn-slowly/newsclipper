# 작업 기록

> 쌓기만 한다. 위를 고치지 않고 아래에 붙인다.

## 2026-08-12 — CLAUDE.md 정리 + 이메일 흔적 제거

- CLAUDE.md: 이메일 참조 9곳 제거, 카테고리 표 중복 제거(PRD 가리킴), 이력→규칙 분리, cron/seen.db/worklog 사실 정정. 11KB→약 7KB
- 삭제: src/email_send.py, config/recipients.yaml.example, templates/ 폴더
- 정리: .env.example 이메일 줄, pyproject.toml email 의존성
- PRD.md: 이메일 항목 완료 처리, worklog 참조 추가
- todolist: 이메일 항목 제거, 번호 재정렬
- 정정: CLAUDE.md 실제 9.5KB (약 7KB는 오기), jinja2 의존성도 제거

## 2026-08-12 — 섹션별 최소 보장 + 섹션당 상한

- _cap_groups를 1단계(돌아가며 최소 보장) + 2단계(중요도별 돌아가며 채우기)로 재작성
- 실측 결함: 8/12 아침 노동 24건 독식 → 수정 후 노동 10, 기후 10, 경남정치 9건

## 2026-08-11 — 같은 사건 묶기 + 30건 상한

- 주제 묶기(오작동) 제거, 제목 유사도 0.45만 사용
- _cap_groups 신설, build_sections를 요약보다 먼저 실행
- 요약 대상: 회당 52→30건, 비용 월 $29→$20 예상

## 2026-08-11 — 발송 대상만 요약 (낭비 제거)

- 꺼진 섹션(여성·청년·복지) 기사도 요약하고 버리던 낭비 발견
- is_sendable 도입 → 발송될 기사만 요약. 요약 대상 79→52건, 월 $41→$29

## 2026-08-11 — 프로젝트 파악 + 문서 실측 정정

- PRD/todolist 6군데를 실측치로 바로잡음 (수집처 개수, 발송량, 비용, 고장 목록)


## 2026-08-12 — Phase 3: 수집 빈틈 복구 + 중앙당 논평 연동

- PRD.md에 Phase 3 기획 추가 (수집 빈틈 복구 + 대응 필요도 + 논평 매칭)
- 수집 빈틈 복구: 프레시안 스크래핑 전환(20건), 참세상 RSS 주소 교체(30건), 구글알리미·MBC경남·민중의소리 정상 확인
- jpnews 구글시트 6열 전환 (날짜·유형·제목·주제·본문·원문링크), 백업 탭 보존
- jpnews 코드 수정: Gemini 모델 교체(gemini-3.5-flash-lite), 신규 메시지만 분류, 분류 실패 시 저장 방지
- jpnews 백필 스크립트 제작: 순번 ID + 실패 건 1건 재시도 + 유형 정규화. 약 4,100건 처리, 2,615건 남음
- newsclipper에 jpnews_reader.py 추가: 구글시트에서 논평 로드 + 키워드 겹침 기반 매칭
- classify.txt에 response_needed(high/medium/none) 추가, classify.py 검증·기본값·적용
- telegram_push.py: 📢 대응필요 + 📌 참고 논평/없음 표시 (그룹 있는/없는 경로 모두)
- GitHub Actions: JPNEWS_SHEETS_CREDENTIALS/JPNEWS_SHEET_ID 시크릿 추가, 수동 실행 성공 (논평 108건 로드, 발송 성공)
- 테스트 37개 전부 통과 (기존 18 + 논평 표시 13 + 분류 파싱 6)

## 2026-08-12 — 여성·청년·복지 섹션 활성화 + jpnews 빈칸 채우기

- section_builder.py: PHASE1_ACTIVE에 3, 4, 5 추가 → 9개 섹션 전부 활성화
- jpnews 구글시트 빈칸 채우기: 2,615건 전부 완료 (이모지 전용 2건은 수동 처리)
- summarize.py: 비용 안전장치 수리 — IMPORTANCE_THRESHOLD_HIGH 4→5 (월 $30 초과 시 실제 작동)