# 통합 보드 배선 절차

이 문서는 배선 도구와 검증 절차를 설명한다. 실제 결과는
`integrated/routing-report.json`과 KiCad 재검사로 확인한다.
배선 연결이 완료되어도 최대 지연·클록 파형·실기 검증을 대신하지 않는다.

## 기존 회로 보호

- 배선 전 통합 PCB의 track/via **4,664개**, footprint **190개**를 고정한다.
- CPU 클록을 포함한 기존 동박의 위치·폭·넷을 자동배선기가 변경하지 못하게 한다.
- 새 부분을 위한 GND zone을 x=448mm까지 확장하고 양면을 재채운다.
- footprint를 움직이거나 pad/net를 지워서 미연결 수를 줄이지 않는다.
- 원래 설계 규칙을 완화하거나 DRC 제외를 추가하지 않는다.
  기존 규칙의 0.2mm clearance, 0.25mm signal, 0.5mm power, 0.8/0.4mm via를 사용한다.
- 후보 파일에 결과를 가져온 뒤 기존 동박/부품 보존과 실제 KiCad DRC를 확인한다.
  소스 보드가 export 이후 변경되었으면 import를 거부한다.

## 로컬 도구

Freerouting **2.5.0**과 Temurin **25.0.5+8 JRE**를 SHA-256으로 검증하여 작업 폴더에만
가져온다. 시스템 Java를 설치하거나 KiCad 전역 설정을 변경하지 않는다.
현재 downloader는 Intel macOS runtime을 고정한다. 다른 플랫폼은 Java 25+ 경로를 별도 지정한다.

Freerouting 2.5.0 native macOS 실행 파일은 이 보드에서 `ComponentOutline`
serialization 오류로 중단되어 JVM 배포본을 사용한다. 오류를 무시하고 후보 보드를
완성된 것으로 취급하지 않는다.

```sh
python3 hardware/redux-color-sound/fetch_router.py
```

배선은 로컬에서 수행한다. `-da`로 analytics를 끄고 REST/MCP 서버도 끈다.
CAD를 외부 배선 서비스에 업로드하지 않는다.

## 재현 예시

기존 작업을 덮어쓰지 않도록 새 work 디렉터리를 사용한다.
아래 명령은 원본 `integrated/` PCB를 직접 변경하지 않는다.

```sh
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  hardware/redux-color-sound/route_board.py prepare \
  --work hardware/redux-color-sound/build/new-route

hardware/redux-color-sound/build/routing-tools/jdk-25.0.5+8-jre/Contents/Home/bin/java \
  -Xmx6g -Djava.awt.headless=true \
  -jar hardware/redux-color-sound/build/routing-tools/freerouting-2.5.0.jar \
  -de hardware/redux-color-sound/build/new-route/route.dsn \
  -do hardware/redux-color-sound/build/new-route/route.ses \
  -da -l en --gui.enabled=false --api_server.enabled=false --mcp_server.enabled=false \
  --user_data_path=hardware/redux-color-sound/build/new-route/router-state \
  --router.automatic_neckdown=false \
  --router.autorouter.max_passes=80

/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  hardware/redux-color-sound/route_board.py import \
  --work hardware/redux-color-sound/build/new-route

python3 hardware/redux-color-sound/check_kicad.py \
  --source hardware/redux-color-sound/build/new-route/candidate \
  --out hardware/redux-color-sound/build/new-route/checked --refill-zones
```

자동배선기의 완료 표시만으로 채택하지 않는다. 후보를 최종 PCB로 반영하기 전:

1. 보호한 기존 동박 4,664개와 모든 부품·패드 형상을 대조한다.
2. source PCB hash가 export 때와 같은지 확인한다.
3. 새 배선과 GND zone을 실제 KiCad에서 다시 읽고 채운다.
4. ERC, physical DRC, schematic parity, 미연결, 제외 항목을 각각 센다.
5. 최종 PCB hash와 보호 검증 결과를 routing report에 기록한다.

`routing_checks.py`는 UUID별 원래 동박과 부품·패드 정보를 독립적으로 대조한다.
클록 배선 변경이나 부품 이동을 놓치지 않도록 실패 조건을 단위 테스트한다.

> **2026-11-24:** `integrated/`가 PLD 디코드로 다시 생성되었다(U64 교체, U66–U68 제거).
> Run 2의 `before.json`/source hash는 이전 PCB 기준이라 import와 채택 검사가 거부한다. 재배선은 새 PCB로 해야 한다.

## Run 2 결과 (2026-11-01 실행, 2026-11-24 분석) — 채택 안 함

`build/route-run2`: Freerouting JVM으로 10시간 10분, 80 pass를 실행했다.
291개 미배선 net으로 시작해 **47개 연결이 미배선**으로 남았고, optimizer는
미완료 보드라서 실행되지 않았다. import 보호 검사는 통과했다. 기존 동박 4,664개와
footprint는 변경되지 않았고, 동박 2,639개가 추가됐다.
`--refill-zones` KiCad 검사 결과는 ERC 0건, DRC **268건**(제외 0)이다.

| 항목 | 수 | 원인 |
| --- | ---: | --- |
| `track_width` | 199 | 새 배선 195개가 0.1874mm, 4개가 0.15mm로 보드 최소 0.2mm 미만 |
| `unconnected_items` | 69 | GND 30, 신호 39 |

- **선폭:** DSN 규칙은 signal 0.25mm, power 0.5mm로 올바르게 export됐다.
  좁은 선은 Freerouting 기본값 `automatic_neckdown`(핀 사이 진입 시 선폭 축소)이
  만든 것이다. 위 재현 명령에 `--router.automatic_neckdown=false`를 추가했다.
  Freerouting의 CLI가 일반 `router.*` 키를 처리하고 해당 설정 이름이 클래스에 있음을
  확인했다. 하지만 실제로 적용됐는지는 **다음 실행의 SES 선폭 분포로 확인해야 한다.**
  neckdown을 끄면 촘촘한 DIP 핀 사이를 지나지 못해 미배선이 늘 수 있다.
- **미배선 신호 39개:** 거의 모두 CPU 주소 버스 `A0..A15`와 확장부 `CS_VA*`,
  `CS_VDATA*` 버스다. 기존 보드에서 확장 영역으로 넘어가는 버스 혼잡으로 보인다.
  pass 수를 늘리기보다 확장 IC 배치를 버스 쪽으로 옮기거나 통로를 확보하는 편이
  효과적일 가능성이 높다. 배치 변경은 `place_extensions.py` 결과와 보호 조건을
  함께 다시 검토해야 한다.
- **GND 30개:** 확장 영역 GND zone island/thermal 연결 문제로 추정된다.
  zone을 넓히거나 via stitching을 추가하는 후보를 검토한다.

**2026-11-24 타이밍 검토 결과, 재배선을 보류한다.** [TIMING_REVIEW.md](TIMING_REVIEW.md)의 8절
(디코드 PLD화, Attribute 주소 경로 변경, 배치 압축, 클록 분리)을 먼저 반영해야 한다.
원래 권고: 재배선은 최악 조건 타이밍 검토(`CIRCUIT.md` "아직 통과하지 않은 조건" 2–6) 뒤에
진행하는 것을 권장한다. 타이밍 결과로 회로나 배치가 바뀌면 10시간짜리 배선을
다시 해야 하기 때문이다.
