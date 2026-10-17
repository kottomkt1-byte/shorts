# Vercel + Railway 배포

Vercel은 정적 편집 화면과 작은 JSON API 프록시를 제공합니다. Railway의 Python/FFmpeg 서비스가 업로드, 분석, 렌더링, SQLite 작업 큐를 처리합니다. 영상은 만료 시간이 있는 파일 링크로 Railway에 직접 전송하므로 Vercel 함수의 요청 크기 제한에 걸리지 않습니다.

## Railway

GitHub `kottomkt1-byte/shorts`의 `main`을 연결합니다. 저장소 루트의 `Dockerfile`과 `railway.json`을 사용하며 `/data`에 영속 볼륨을 연결합니다. SQLite와 영상이 같은 볼륨에 있으므로 **복제본은 1개**로 유지합니다. 컨테이너 시작 시 볼륨 소유권을 설정하고 UID 10001 사용자로 앱을 실행합니다. 건강 상태 확인 경로는 `/healthz`입니다.

필수 환경 변수:

| 변수 | 설정 |
|---|---|
| `AUTO_SHORTS_ACCESS_MODE` | `public`: 로그인 없이 브라우저별 작업 공간 생성 |
| `AUTO_SHORTS_PUBLIC_URL` | Railway 서비스의 정확한 HTTPS 주소 |
| `AUTO_SHORTS_ORIGINS` | 편집기를 여는 HTTPS 주소, 여러 개면 쉼표 구분, 경로·와일드카드 제외 |
| `AUTO_SHORTS_TRANSFER_SECRET` | 최소 32자의 무작위 서버 내부 서명 비밀값 |
| `AUTO_SHORTS_DATA` | `/data` |
| `PORT` | `8080` |
| `AUTO_SHORTS_CONCURRENCY` | `1` |

접속 키를 배포하거나 입력할 필요가 없습니다. 익명 세션 쿠키로 브라우저별 파일·작업 기록을 구분합니다. 브라우저 데이터를 지우거나 다른 브라우저를 쓰면 별도 공간이 생성됩니다. 주소를 아는 사람은 편집기를 사용할 수 있습니다. 파일 전송 링크는 해당 파일과 작업 공간에만 유효하며, 업로드 링크는 5~10분, 재생·다운로드 링크는 115~120분 후 만료됩니다. 새로고침하면 갱신됩니다. 서버 내부 서명값을 프런트엔드 환경 변수나 저장소에 넣지 마세요.

Docker 이미지에는 빌드된 편집 화면도 들어 있습니다. Vercel 연결 전에는 Railway 주소를 `AUTO_SHORTS_ORIGINS`에 넣어 직접 열 수 있습니다. Vercel 도메인이 확정되면 두 주소를 모두 허용하고 서버를 재배포합니다. 두 주소의 브라우저 세션은 서로 별개입니다.

## Vercel

1. 같은 GitHub 저장소를 가져옵니다. 프레임워크는 Other, 루트는 저장소 루트입니다. `vercel.json`의 설치·빌드 명령을 사용합니다.
2. Vercel 환경 변수 `SHORTS_BACKEND_ORIGIN`에 실행 중인 Railway HTTPS 주소만 설정합니다.
3. 배포합니다. `npm run build:vercel`이 Build Output API 형식의 `.vercel/output`을 생성합니다. `/api/*`는 Railway로 전달하고 영상 전송은 브라우저에서 Railway로 직접 수행합니다.
4. 확정된 Vercel 프로덕션 주소를 Railway의 `AUTO_SHORTS_ORIGINS`에 추가합니다. 링크로 접속할 수 있도록 Vercel 프로덕션 배포의 접근 보호 설정을 확인합니다.
5. Vercel 주소에서 업로드, 미리보기, MP4 출력·다운로드를 확인합니다. 도메인이 다른 프리뷰 배포는 해당 주소를 별도로 허용해야 합니다.

## 현재 요금제의 저장 공간

연결된 Railway 계정은 볼륨을 최대 **500MB**까지 만들 수 있었습니다. 작은 영상으로 테스트하도록 다음 배포 환경 값을 사용합니다. 로컬 기본값(파일당 500MB, 작업 공간 10GB, 72시간 보관)은 유지됩니다.

| 변수 | 소규모 배포 값 |
|---|---|
| `AUTO_SHORTS_MAX_UPLOAD_MB` | `25` |
| `AUTO_SHORTS_QUOTA_MB` | `400` |
| `AUTO_SHORTS_TTL_HOURS` | `6` |
| `AUTO_SHORTS_MIN_FREE_MB` | `64` |

500MB는 모든 브라우저가 공유하는 전체 볼륨 용량입니다. 작업 공간당 400MB를 보장하는 의미가 아닙니다. 여유 공간이 부족하면 새 작업을 거부하고 진행 중인 렌더를 중단해 데이터베이스 공간을 남깁니다. 원본·결과·임시 파일이 함께 공간을 사용하므로 긴 영상이나 여러 배치 작업에는 볼륨 확장이 필요합니다. 파일 보관 기간은 화면에 표시되며, 완성본은 다운로드해 보관하세요. 작은 볼륨에서는 템플릿을 하나씩 출력하는 방식을 권장합니다.

## 확인 방법

```bash
docker build -t shorts-renderer .
SHORTS_BACKEND_ORIGIN=https://your-renderer.up.railway.app npm run build:vercel
python -m unittest discover -s tests -v
```

실제 배포에서는 컨테이너 시작, `/healthz`, 편집 화면, 원본 업로드·분석, 1080p 렌더, Range 재생, MP4 다운로드, 새로고침 후 작업 복원, 다른 브라우저와의 분리를 확인합니다. 검증 범위와 결과는 `TEST_REPORT.md`에 구분해 기록합니다.
