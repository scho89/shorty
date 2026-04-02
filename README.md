# Shorty

간단한 **Django 기반 URL 단축 서비스**입니다.

사용자는 로그인 후 자신의 도메인을 등록하고, DNS TXT/CNAME 검증을 거쳐 커스텀 단축 URL을 생성할 수 있습니다.

---

## 주요 기능

- 회원가입 / 로그인
- 단축 URL 생성, 수정, 삭제
- 커스텀 도메인 등록 및 소유권 확인
- 방문 수 집계
- 워드클라우드 기반 사용량 시각화

---

## 기술 스택

- Python 3.12
- Django 4.1.10
- SQLite (로컬 개발 기본값)
- `django-environ`
- `dnspython`

> 운영 환경의 `prod` 설정에서는 별도 DB 연결을 위해 `pymssql`이 필요할 수 있습니다.

---

## 프로젝트 구조

```text
shorty/
├─ common/                # 인증, URL/도메인 관리 뷰
├─ config/                # Django 설정 및 URL 진입점
├─ shorty/                # 단축 URL 모델/리다이렉트 로직
├─ templates/             # 템플릿
├─ static/                # 정적 파일
├─ manage.py
└─ requirements.txt
```

---

## 로컬 실행 방법 (Windows 기준)

### 1) 가상환경 활성화

```powershell
.\.venv\Scripts\Activate.ps1
```

가상환경이 없다면:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) 패키지 설치

```powershell
pip install -r requirements.txt
```

### 3) 환경 변수 파일 생성

프로젝트 루트에 `.env` 파일을 만들고, `.env.example` 내용을 복사해 값만 채웁니다.

### 4) 마이그레이션 적용

```powershell
python manage.py migrate
```

### 5) 개발 서버 실행

```powershell
python manage.py runserver
```

기본 접속 주소:

- `http://127.0.0.1:8000/`

---

## 테스트 및 점검

### Django 설정 점검

```powershell
python manage.py check
```

### 테스트 실행

```powershell
python manage.py test common shorty
```

---

## 환경 변수 설명

기본적으로 `config.settings`는 아래 규칙으로 동작합니다.

- `DJANGO_SETTINGS_PROFILE=local` 또는 미지정 → `config/settings/local.py`
- `DJANGO_SETTINGS_PROFILE=prod` → `config/settings/prod.py`

주요 환경 변수:

| 변수명 | 설명 |
|---|---|
| `SECRET_KEY` | Django 시크릿 키 |
| `DEBUG` | 개발 모드 여부 (`True` / `False`) |
| `ALLOWED_HOSTS` | 허용 호스트 목록 |
| `DYNAMIC_ALLOWED_HOSTS_CACHE_SECONDS` | 운영에서 DB 기반 허용 도메인 캐시 시간(초) |
| `RECAPTCHA_SITE_KEY` | Google reCAPTCHA 사이트 키 |
| `RECAPTCHA_SECRET` | Google reCAPTCHA 시크릿 키 |
| `SSL_LIST` | 인증 완료 도메인을 기록할 파일 경로 |
| `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` | 운영 DB 설정 (`prod`) |

---

## 운영 배포 메모

- 운영 배포 시 `DEBUG=False`를 사용하세요.
- `ALLOWED_HOSTS`는 `*` 대신 실제 도메인만 지정하세요.
- 운영에서는 `host_allowed=True` 인 도메인이 DB에서 자동 반영되어 재시작 없이 허용됩니다. 반영 주기는 `DYNAMIC_ALLOWED_HOSTS_CACHE_SECONDS`로 조절합니다.
- `prod.py` 사용 시 DB 드라이버와 연결 정보를 먼저 준비하세요.
- 로그는 기본적으로 `logs/mysite.log`에 기록됩니다.

---

## 최근 반영된 개선 사항

- 사용자 소유 도메인만 URL 생성 가능하도록 권한 강화
- 삭제/검증 요청을 `POST + CSRF`로 변경
- DNS 검증 재시도 로직 보정
- 테스트 추가 및 마이그레이션 충돌 정리
