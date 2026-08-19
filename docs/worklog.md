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
- jpnews 구글시트 빈칸 채우기: 2,615건 중 2,613건 완료 (99.9%), 2건은 분류 불가
- jpnews 나머지 2건 수동 처리 (이모지 전용 메시지 → "기타"로 채움, 빈 행 0건 달성)
- summarize.py: 비용 안전장치 수리 — IMPORTANCE_THRESHOLD_HIGH 4→5 (월 $30 초과 시 실제 작동)
- 비용 안전장치 테스트 3개 추가 ($30 경계에서 4점/5점 동작 검증, 테스트 40개 통과)

## 2026-08-13 — Phase 4: 실용성 강화 (이슈 추적 + 속보 알림 + 주간 요약)

- main.py: --mode CLI 인자 추가 (briefing / alert / weekly 지원)
- issue_tracker.py: 최근 7일 DB 기사 제목 유사도(0.45) 기반 이슈 경과 추적 ("📋 N일째 진행 중") 추가
- telegram_push.py: 이슈 경과 맥락 표시 + 속보(🚨) 및 주간 요약(📊) 메시지 포맷 함수 추가
- storage.py: alert_seen 테이블 추가 (속보 점검 중복 발송 및 재분류 방지), get_recent_articles 추가
- weekly_summary.py: 지난 7일 기사 분석 및 Sonnet 4.6 기반 월요일 주간 리포트 생성 기능 추가
- Workflows: .github/workflows/alert-check.yml (3시간 간격) 및 weekly-summary.yml (월요일 8시 KST) 생성
- 테스트: 총 46개 테스트 통과 (새 기능 단위 테스트 6개 추가)

## 2026-08-19 — 양산시 집중 프로토타입 (수집 보강 + 전용 섹션)

- feeds.yaml: 양산 지역지 그룹 추가 — 양산신문·양산뉴스파크 RSS (실측: 24시간 내 50건/2건 수집 확인)
- keywords.yaml: regions에 양산 세부 지명(물금·웅상·덕계·평산·서창·사송), regional_politics에 양산시의회·양산시장·양산시청·웅상출장소, prefilter_keywords에 양산 키워드 추가
- classify.txt: 양산 관련 기사 판정 지침 추가 (지명/기관명 포함 시 scope=gyeongnam)
- section_builder.py: 섹션 10 "📍 양산시 집중 소식" 신설 — is_yangsan_article() 하나로 편입/제외 판정 (중복·누락 방지), _matches_section에 섹션 번호 전달
- 테스트: 양산 전용 섹션 5개 추가 (배치·제외·누락 없음·지명 판정·가산 후 배치), 총 59개 통과