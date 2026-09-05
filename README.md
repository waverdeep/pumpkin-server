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
| `GOOGLE_CLIENT_ID` `GOOGLE_CLIENT_SECRET` | 구글 OAuth 클라이언트. 비어 있으면 로그인 버튼이 꺼진다 |
| `PUBLIC_ORIGIN` | 리다이렉트 URI 기준 주소. 로컬 `http://127.0.0.1:5173`, 배포는 deploy.sh 가 `https://pumpkin.zzam.today` 로 넣는다 |
| `SESSION_SECRET` | 세션 쿠키 서명 키 |
| `LOGIN_REQUIRED` | `true` 면 바구니 만들기에 로그인 필수. 로컬 기본 false, 배포 기본 true |

## API

| 메서드 | 경로 | 누가 | 하는 일 |
|---|---|---|---|
| POST | `/api/baskets` | 아무나 | 바구니 만들기. 주인 쿠키 발급 |
| GET | `/api/me` | 주인 | 내 바구니 (없으면 `null`) |
| GET | `/api/baskets/{slug}` | 아무나 | 이름·개수·껍질만. 내용은 절대 안 내려감 |
| GET | `/api/baskets/{slug}/curses` | 아무나 | 아직 안 걸린 저주 카드 |
| POST | `/api/baskets/{slug}/candies` | 아무나 | 사탕 넣기 (로그인 없음). `sender`는 선택, 12자, 비우면 익명 |
| GET | `/api/baskets/{slug}/candies` | 주인 | 개봉. 서버 시각이 `OPEN_AT`을 지나야 내려줌 (아니면 423) |

| GET | `/api/auth/google/start?next=/` | 아무나 | 구글 로그인 시작 (scope `openid` 뿐) |
| GET | `/api/auth/google/callback` | 구글 | 콜백. `sub` 로 users upsert, 세션 쿠키 발급 |
| POST | `/api/auth/logout` | 주인 | 세션·익명 쿠키 삭제 |

## 로그인

받는 정보는 구글 `sub` 하나. 이메일·프로필을 요청하지 않아 동의 화면에 민감 범위가 없고 검수가 필요 없다. `users` 는 `provider` + `provider_id` 로 식별하고 계정 통합은 하지 않는다.

- 로그인 사용자: `pk_session` 쿠키 (`<user_id>.<만료>.<hmac>`, `SESSION_SECRET` 으로 서명)
- 익명 사용자(로컬·테스트): `pk_owner` 쿠키. `LOGIN_REQUIRED=false` 일 때만 새로 발급된다
- 카톡 인앱 브라우저는 구글이 OAuth 를 막는다. 웹이 `kakaotalk://web/openExternal` 로 바깥 브라우저를 연다

구글 콘솔 설정: OAuth 동의 화면(외부, 범위 없음, 프로덕션 게시) → 웹 애플리케이션 클라이언트. 승인된 리디렉션 URI 에 `https://pumpkin.zzam.today/api/auth/google/callback` 과 `http://127.0.0.1:5173/api/auth/google/callback`.

## 배포 — Cloud Run

```bash
./deploy.sh                    # gcloud 로그인·프로젝트 설정된 상태에서
MIN_INSTANCES=1 ./deploy.sh    # 개봉일 전후. 콜드 스타트를 없앤다
```

`--source .` 로 Cloud Build 가 `Dockerfile` 을 빌드한다. DB 비밀번호는 Secret Manager `pumpkin-db-password` 에 들어가고 나머지는 환경변수. 배포가 끝나면 서비스 주소를 Cloudflare Workers 의 `API_ORIGIN` 에 넣는다.

마이그레이션은 배포와 분리되어 있다. 스키마가 바뀌면 로컬에서 `uv run alembic upgrade head` 를 먼저 돌리고 배포한다.

개봉 시각을 정하면 `.env` 의 `OPEN_AT` 을 채우고 다시 배포한다.
