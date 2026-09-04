# pumpkin-server

사탕바구니 API. FastAPI + SQLAlchemy 2 + Alembic, DB는 Supabase Postgres의 `pumpkin` 스키마.

## 실행

```bash
uv sync
cp .env.example .env   # DB 접속 정보 채우기
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

문서: http://127.0.0.1:8000/api/docs

## 테스트

`.env`의 DB에 직접 붙어서 돌고, 만든 데이터는 지운다.

```bash
uv run pytest
```

## 마이그레이션

스키마는 반드시 Alembic으로만 바꾼다. 모델(`app/models.py`)을 고친 뒤:

```bash
uv run alembic revision --autogenerate -m "무엇을 바꿨는지"
uv run alembic upgrade head
uv run alembic check      # 모델과 DB가 같은지 확인
```

같은 DB에 다른 서비스 스키마가 있으므로 `alembic/env.py`가 `pumpkin` 스키마만 들여다본다.

## 설정 (.env)

| 키 | 뜻 |
|---|---|
| `DB_HOST` `DB_PORT` `DB_USER` `DB_PASSWORD` `DB_NAME` `DB_SSL` `DB_SCHEMA` | Supabase 풀러 주소. 6543(트랜잭션 모드)이라 prepared statement를 끄고 쓴다 |
| `OPEN_AT` | 개봉 시각(ISO 8601). 비워두면 언제든 개봉 가능 = 테스트 모드. 예 `2026-10-31T20:00:00+09:00` |
| `COOKIE_SECURE` | 배포 시 `true` |
| `THROW_RATE_PER_MINUTE` | IP당 분당 사탕 넣기 횟수 (기본 20) |

## API

| 메서드 | 경로 | 누가 | 하는 일 |
|---|---|---|---|
| POST | `/api/baskets` | 아무나 | 바구니 만들기. 주인 쿠키 발급 |
| GET | `/api/me` | 주인 | 내 바구니 (없으면 `null`) |
| GET | `/api/baskets/{slug}` | 아무나 | 이름·개수·껍질만. 내용은 절대 안 내려감 |
| GET | `/api/baskets/{slug}/curses` | 아무나 | 아직 안 걸린 저주 카드 |
| POST | `/api/baskets/{slug}/candies` | 아무나 | 사탕 넣기 (로그인 없음). `sender`는 선택, 12자, 비우면 익명 |
| GET | `/api/baskets/{slug}/candies` | 주인 | 개봉. 서버 시각이 `OPEN_AT`을 지나야 내려줌 (아니면 423) |

주인 식별은 `pk_owner` httponly 쿠키. `users` 테이블은 `provider` + `provider_id`만 갖고, 지금은 `provider='anon'`. 구글 로그인은 같은 테이블에 `provider='google'`로 붙인다.

## 배포 — Cloud Run

```bash
./deploy.sh                    # gcloud 로그인·프로젝트 설정된 상태에서
MIN_INSTANCES=1 ./deploy.sh    # 개봉일 전후. 콜드 스타트를 없앤다
```

`--source .` 로 Cloud Build 가 `Dockerfile` 을 빌드한다. DB 비밀번호는 Secret Manager `pumpkin-db-password` 에 들어가고 나머지는 환경변수. 배포가 끝나면 서비스 주소를 Cloudflare Workers 의 `API_ORIGIN` 에 넣는다.

마이그레이션은 배포와 분리되어 있다. 스키마가 바뀌면 로컬에서 `uv run alembic upgrade head` 를 먼저 돌리고 배포한다.

개봉 시각을 정하면 `.env` 의 `OPEN_AT` 을 채우고 다시 배포한다.
