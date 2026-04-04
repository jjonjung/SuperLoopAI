# GameAITool

UE5 게임 프로젝트 전용 AI 개발 자동화 CLI 툴.  
**어떤 UE5 프로젝트에서도** `--project` 옵션 하나로 동작합니다.

---

## 기능

| 커맨드 | 설명 |
|--------|------|
| `review` | UE5 C++ 코드 AI 리뷰 (심각도 분류 + 수정 제안) |
| `optimize` | 플랫폼별(mobile/pc/console) 성능 최적화 분석 |
| `qa` | 기능별 QA 시나리오 자동 생성 |
| `lint` | 에셋 네이밍 컨벤션 린트 (Epic Games 표준) |
| `doc` | C++ 헤더 → 한국어 개발자 문서 자동 생성 |
| `workflow` | 위 4단계 통합 파이프라인 |

## 설치

```bash
pip install -r requirements.txt
set ANTHROPIC_API_KEY=sk-ant-...
```

## 사용법

```bash
# 프로젝트 지정 (필요 시 --project 옵션)
python main.py --project C:/path/to/MyGame review PlayerCharacter.cpp

# 현재 디렉토리가 UE5 프로젝트 내부면 --project 생략 가능
cd C:/path/to/MyGame
python path/to/GameAITool/main.py review PlayerCharacter.cpp

# 예시
python main.py --project ../Infinity review BattleManager.cpp
python main.py --project ../Infinity optimize AiBrainComponent.cpp --target mobile
python main.py --project ../Infinity qa "킬/데스 집계 시스템"
python main.py --project ../Infinity lint
python main.py --project ../Infinity doc BattleManager.h
python main.py --project ../Infinity workflow BattleManager --target mobile

python main.py --project ../CITRUSH-UE review NavSystemDataComponent.cpp
python main.py --project ../CITRUSH-UE workflow PlayerController --target pc
```

## 프로젝트 자동 감지 규칙

1. `--project PATH` 지정 → PATH 내 `.uproject` 탐색
2. 현재 디렉토리부터 상위 방향으로 `.uproject` 탐색
3. 현재 디렉토리 하위 방향으로 `.uproject` 탐색
4. 탐색 실패 시 현재 디렉토리 사용
