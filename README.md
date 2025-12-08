# 📰 Political News Clipper

정의당 경남도당 뉴스 클리핑 자동화 서비스

## 🎯 주요 기능

- **자동 뉴스 수집**: Google News RSS를 통해 키워드 조합 기반 뉴스 자동 수집
- **AI 분석**: Google Gemini API를 활용한 뉴스 관련성/중요도 평가 및 요약
- **노션 자동 발행**: 분석된 뉴스를 노션 데이터베이스에 자동 등록
- **스케줄링**: 매일 오전 7시, 오후 6시 자동 실행

## 📁 프로젝트 구조

```
newsclipper/
├── src/
│   ├── main.py              # 메인 실행 파일
│   ├── scheduler.py         # 스케줄러
│   ├── collector/           # 뉴스 수집 모듈
│   │   ├── google_news.py   # Google News RSS
│   │   ├── naver_news.py    # 네이버 뉴스 API
│   │   └── models.py        # 데이터 모델
│   ├── analyzer/            # AI 분석 모듈
│   │   ├── gemini_client.py # Gemini API 클라이언트
│   │   └── analyzer.py      # 분석 로직
│   ├── publisher/           # 노션 연동 모듈
│   │   └── notion_client.py # 노션 API 클라이언트
│   ├── storage/             # 데이터 저장
│   │   └── database.py      # SQLite 관리
│   └── utils/               # 유틸리티
│       ├── config.py        # 설정 관리
│       └── logger.py        # 로깅
├── config/
│   ├── config.json          # 키워드 설정
│   └── prompts/             # AI 프롬프트
├── scripts/
│   ├── run_once.py          # 수동 실행
│   └── test_collection.py   # 수집 테스트
├── tests/                   # 테스트 코드
├── data/                    # SQLite DB
├── logs/                    # 로그 파일
├── .env                     # 환경 변수 (생성 필요)
├── requirements.txt         # 의존성
└── README.md
```

## 🚀 설치 및 설정

### 1. 의존성 설치

```bash
cd newsclipper
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 생성하고 다음 내용을 입력:

```bash
# 필수
GOOGLE_API_KEY=your_google_ai_api_key
NOTION_API_KEY=your_notion_integration_token
NOTION_DATABASE_ID=your_notion_database_id

# 선택 (네이버 API)
NAVER_CLIENT_ID=your_naver_client_id
NAVER_CLIENT_SECRET=your_naver_client_secret

# 설정
LOG_LEVEL=INFO
RELEVANCE_THRESHOLD=60
```

### 3. 노션 설정

1. [Notion Integrations](https://www.notion.so/my-integrations)에서 새 Integration 생성
2. 노션에서 데이터베이스 생성 (아래 속성 필요):
   - 제목 (Title)
   - 카테고리 (Select)
   - 중요도 (Number)
   - 키워드 (Multi-select)
   - 언론사 (Rich text)
   - 발행일시 (Date)
   - 원문링크 (URL)
   - 대응완료 (Checkbox)
3. 데이터베이스에 Integration 연결
4. 데이터베이스 ID를 `.env`에 입력

## 💻 사용법

### 뉴스 수집 테스트 (API 키 불필요)

```bash
python scripts/test_collection.py
```

### 수동 실행 (1회)

```bash
python scripts/run_once.py
```

### 스케줄러 실행

```bash
python src/scheduler.py
```

## ⚙️ 키워드 설정

`config/config.json`에서 키워드 조합을 수정할 수 있습니다:

```json
{
  "keyword_combinations": [
    {
      "name": "노동-경남",
      "issues": ["노동", "산재", "산업재해"],
      "regions": ["경남", "창원", "김해"],
      "category": "노동"
    }
  ]
}
```

## 📊 비용 예상

| 항목 | 월 예상 비용 |
|------|-------------|
| Gemini API | 무료 (일일 한도 내) |
| GitHub Actions | 무료 |
| 노션 | 무료 |
| **합계** | **무료** |

> 💡 Gemini API는 무료 티어에서 분당 15회, 일일 1,500회 요청이 가능합니다.

## 🔧 문제 해결

### RSS 수집이 안 될 때
- 인터넷 연결 확인
- Google News 서비스 상태 확인

### 노션 발행 실패
- Integration 권한 확인
- 데이터베이스 속성 이름 확인

### AI 분석 오류
- Google AI API 키 유효성 확인
- API 사용량 한도 확인 (무료: 분당 15회, 일일 1,500회)

## 📝 라이선스

MIT License

