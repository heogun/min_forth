# Redux 1.4 — Attribute Color + SN76489 통합 보드

상태: **컬러·SN76489 통합 회로도와 PCB 부품/net 배치 초안이 추가됨. 배선·최악 조건 타이밍 검증 미완료, 제조 금지.**

실제 추가 회로와 현재 검증 상태: **[CIRCUIT.md](CIRCUIT.md)**.
KiCad에서는 `integrated/8-Bit CPU 32k.kicad_pro`를 연다.
`cad/`는 경고를 해결한 기존 흑백 보드 기준본이며, 추가 회로가 있는 프로젝트와 구분한다.

2026-10-30 사용자 선택: 기존 Revision 1.4 Redux를 기반으로 컬러와
SN76489 음원을 하나의 새 PCB에 통합한다. 원본 `minimal64/`는 변경하지 않는다.
이 문서는 실기 동작, 타이밍 여유, 제조 가능성을 보증하지 않는다.

## 1. 범위와 불변 조건

- CPU 8MHz, 기존 명령·마이크로코드 실행 사이클을 유지한다.
- 컬러·음원 때문에 CPU 클록을 게이팅하거나 WAIT/DMA를 추가하지 않는다.
- 기존 비트맵 접근 대역폭을 색상 읽기로 나눠 쓰지 않는다.
- 400×240 표시, 기존 PS/2·UART·확장 포트를 유지한다.
- 컬러는 1bpp 비트맵 + 영역별 전경/배경 각 16색이다. 픽셀별 독립 4bpp가 아니다.
- 음원은 SN76489 계열 전용 IC를 사용한다. AY, TTS, SD, 조이스틱은 이번 범위 밖이다.
- DIP/관통형 중심을 유지하되, 정확한 주문번호·소켓·풋프린트는 회로도 확정 후 결정한다.
- 리셋 중/후 컬러 비활성 및 하드웨어 오디오 mute를 목표로 한다.

무대기 CPU와 무제한 주변장치 쓰기는 다르다. 음원·Attribute 쓰기 간격과
pending 데이터의 수명은 소프트웨어가 지켜야 한다. 폴링·지연 명령을 사용하면
그 프로그램의 CPU 시간은 소비된다. 모든 전송을 CPU 비용 없이 처리한다는 뜻이 아니다.

## 2. 확인한 기준 자료

### Redux

- 로컬 원본 저장소 커밋: `1a59c95695d1a6a6147584465ee87803fe9387da`.
- `minimal64/Revision 1.4 Redux/Schematics.pdf`: Control Logic, Memory and MAR, VGA.
- `minimal64/Revision 1.4 Redux/KiCAD9/`: 기존 KiCad 9 프로젝트.
- `minimal64/Revision 1.4 Redux/Programs/asm/vga.asm`: ViewPort `0x430c`.
- `minredux/src/lib.rs`: 64바이트 stride, ViewPort `(96,12)`, 400×240 crop.

기존 VGA는 U36 AS6C62256, U35 HC166, U37/U39 HC590, U38/U40/U41 HC574를 쓴다.
영상 읽기 예약 구간과 CPU 영상 쓰기를 유지하면서 색상 RAM을 병렬 읽는 방향이다.
`~VGA_GET` 종료 시 스캔 카운터도 갱신되므로 같은 에지에서 색상을 무심코
래치하면 다음 바이트 주소/현재 픽셀 간 정렬 문제가 생길 수 있다.

### SN76489 참고 보드

[hans61/Minimal-64x4-Expansion](https://github.com/hans61/Minimal-64x4-Expansion),
검토 커밋 `92207bfac9450aeef2b72a4420adfdd4c44e60af`:

- `hardware/Rev.6/README.md`: 주소 배치와 과거 제어 신호 오류 설명.
- `hardware/Rev.7/eagle/expansion-sn76489-kempton-sd-rev7.sch`: Eagle XML의 부품·net 연결 확인.
- `software/sn76489/BirdSound.asm`: 데이터 기록 후 제어 bit 1 assert/deassert 순서 확인.

확인 사항:

- `0xFEE0` 데이터 HC574, `0xFEE2` 제어 HC173, 제어 bit 1로 음원 쓰기를 제어한다.
- 실제 음원 `~CE`는 GND, HC173 Q2를 HC04로 반전한 신호가 `~WE`로 들어간다.
- CPU bit 0은 SN의 **D7**, CPU bit 7은 SN의 **D0**에 연결된다.
  TI 표기의 D0가 MSB이므로 이름만 보고 같은 번호끼리 연결하면 안 된다.
- 원문은 초기 리비전의 HC74 기반 CS 제어에 드문 오류가 있었으며 Rev.6에서
  HC173으로 바꿨다고 설명한다. 이전 회로로 단순화하지 않는다.
- 음원 경로의 부품 종류: HC30, HC04, HC11, HC138, HC574, HC173, SN76489,
  LM386. 다른 기능을 제외해도 **앰프 포함 8개 IC + 발진기 모듈**인 참고 구조다.
  이는 통합 보드의 확정 BOM이나 최소 칩 수 증명이 아니다.
- 4MHz/3.579MHz 별도 발진기와 확장 포트 클록을 선택하는 연결이 있다.
  원본 보드용 소프트웨어의 NOP 시간은 Redux에 그대로 적용하지 않는다.

[TI SN76489AN 데이터시트 사본](https://map.grauw.nl/resources/sound/texas_instruments_sn76489an.pdf):
5V, 최대 4MHz, open-collector READY, 대략 32 입력 클록의 데이터 처리,
D0=MSB를 확인할 기준이다. SN76494 등은 같은 조건으로 대체하지 않는다.
최종 설계 전에 정확한 구매 칩의 데이터시트 전체 타이밍 표/파형을 확인한다.

[michaelkamprath/minimal-64x4-expansion-cards](https://github.com/michaelkamprath/minimal-64x4-expansion-cards)는
TMS5220C 음성 합성·곱셈기·타이머의 참고 자료다. SN 음원이나 컬러 회로의
검증 자료로 취급하지 않는다. 이번 초안에는 외부 회로 파일을 복사하지 않았다.

## 3. 컬러 주소와 화면 좌표

내부 VRAM은 512×256에 해당하는 **16KB** 비트맵 공간이다.
U36의 부품 용량이 32KB인 것과 실제 연결된 주소 공간은 구분한다.
표시/소프트웨어 ViewPort는 그 안의 `(96,12)`에서 시작하는 400×240 영역이다.

Attribute는 64열×32행, **2KB**, 한 바이트에 `background[7:4] | foreground[3:0]`.
별도 SRAM 한 개를 사용하고 CPU RAM/비트맵을 대신 사용하지 않는다.

**권장 주소식: 글자 행과 일치하도록 세로 위상 +4 (mod 256)**

```text
x, y       = 내부 비트맵 좌표 (0..511, 0..255)
attr_x     = x >> 3
attr_y     = ((y + 4) & 255) >> 3
attr_index = attr_y * 64 + attr_x       # 0..2047

ViewPort 글자 (column, row), column=0..49, row=0..29:
attr_index = (row + 2) * 64 + column + 12
```

이렇게 하면 400×240 화면의 50×30개 8×8 글자 영역과 색상이 일치한다.
보이는 1,500개 Attribute는 2KB 배열 안에서 stride 64로 배치된다.
자동으로 연속된 1,500바이트가 되는 것은 아니다.

단순히 `y >> 3`만 배선하면 ViewPort가 y=12에서 시작하기 때문에 31개
Attribute 행에 걸치고 글자 중간에서 색이 바뀐다. 앞선 단순 50×30 설명에는
이 위상 보정 조건이 빠져 있었다. 보정 로직의 지연·칩 수를 BOM에 포함해야 한다.

### 영상 데이터 경로

```text
스캔 주소 ─┬─ 기존 VRAM → 기존 HC166 → pixel ──────────┐
           └─ Attribute 주소 → SRAM → 색상 레지스터 ──┤
                                                     ↓
                                    전경/배경 선택 → blanking → RGB DAC
CPU → 주소/데이터 유지 → 영상 읽기 외 구간에 Attribute 쓰기
```

- SRAM 읽기는 기존 비트맵 읽기와 병렬 수행한다. 픽셀마다 SRAM을 읽지 않는다.
- 색상 레지스터는 CPU SRAM 쓰기 중에도 현재 출력 색상을 유지한다.
- 읽기/쓰기 주소 MUX, 데이터 래치, pending 제어가 필요하다.
- 새 Attribute 요청이 미처리 요청을 덮어쓰지 않도록 최소 간격 또는 상태 읽기를 정의한다.
- CPU 쓰기 시점과 SRAM commit이 달라질 경우 주소와 데이터가 함께 보존되어야 한다.
- 실제 추가 회로는 기존 VREG의 주소·데이터 유지 및 영상 쓰기 slot을 공유한다.
  제어 bit 2로 비트맵/Attribute 쓰기를 선택하고, 쓰기 캡처 시 plane도 함께 저장한다.
- SRAM 전원 투입 내용은 미정이다. 초기화 전에는 컬러 출력을 활성화하지 않는다.
- 비표시 구간은 모든 RGB를 검정으로 강제한다. HSYNC/VSYNC만으로 active-video를
  판정하거나 기존 VRAM의 0 데이터를 검정 대신 사용하지 않는다.
- ViewPort 외 테두리 색상을 허용할지는 미정이다. 400×240 crop을 곧바로
  회로의 실제 수평·수직 blanking 경계라고 가정하지 않는다.
- RGBI 계열 고정 16색 DAC를 기본 후보로 한다. CGA의 정확한 갈색 보정/색상표
  호환은 아직 약속하지 않는다. 75Ω 부하에서 0..약 0.7V를 검증해야 한다.

## 4. SN76489 데이터 경로

```text
CPU BUS → HC574 데이터 래치 → SN76489 → AC 결합/볼륨 → 오디오 출력
CPU 제어 쓰기 → 리셋 가능한 제어 레지스터 → ~WE
독립 발진기 → SN CLK
```

- 5V DIP-16 SN76489AN을 우선 검토 대상으로 한다. 계열 내 다른 칩은 재검토한다.
- 독립 **3.579545MHz 발진기**를 우선 후보로 한다. 4MHz 기준 음악 데이터는
  음높이 값을 변환해야 한다. 기존 CPU 클록선을 음원 부하로 직접 사용하지 않는다.
- `f = clock / (32 * N)`, 일반 톤 주기 `N=1..1023`. N=0 및 잡음 동작은 별도 검증한다.
- 데이터 유지 → 쓰기 assert → 처리 완료 → 쓰기 deassert → 다음 데이터 순서로 제어한다.
- 약 32클록은 설계 참고값일 뿐 보증 최대 지연이 아니다. 정확한 칩의 READY/파형과
  여유를 검토해 쓰기 폭 및 다음 전송 조건을 확정한다.
- READY를 CPU 클록/WAIT에 연결하지 않는다. 사용한다면 pull-up 및 TTL→HC 입력
  임계값 적합성을 확인하고, 소프트웨어 상태 입력으로 읽도록 한다.
- 단일 래치는 FIFO가 아니다. 전송 중 데이터 갱신 금지 조건을 드라이버에 명시한다.
- SN에는 시스템 reset으로 모든 음량을 확실히 지우는 인터페이스가 없으므로,
  부팅 시 소프트웨어가 `0x9f, 0xbf, 0xdf, 0xff`를 보내기 전까지 아날로그 경로를
  하드웨어 mute한다. 제어 래치만 초기화해서 무음을 보장한다고 주장하지 않는다.
- 기본 출력은 외부 앰프에 연결 가능한 오디오 출력을 우선 검토한다.
  온보드 LM386 스피커 앰프는 선택 실장 후보이며, 헤드폰 출력과 동일시하지 않는다.

## 5. 주소 배치 — 추가 회로 초안

기존 참고 보드와의 음원 제어 관례를 일부 유지할 후보:

| 주소 | 후보 역할 |
| --- | --- |
| `0xFEE0` | 음원 데이터 래치 |
| `0xFEE1` | 상태 읽기 — READY/Attribute mode/color enable/audio enable |
| `0xFEE2` | 제어 레지스터 — bit 0 컬러, bit 1 음원 write, bit 2 Attribute mode, bit 3 unmute |
| `0xFEE3` | 미할당, 참고 보드 SPI와 겹치므로 함부로 재사용하지 않음 |
| `0xFEE4` | 예약 — 초기의 간접 주소 포트안은 채택하지 않음 |
| `0xFEE5` | 예약 |
| `0xFEE6` | 예약 |
| `0xFEE7` | 미할당 |

- 자동 증가·Attribute CPU read-back은 기본 요구사항에 넣지 않는다. 필요 시 비용 평가한다.
- `0xFEE8..0xFEEF`는 bit 3 미디코딩 alias다. 실제 RAM 제외 범위는 `0xFEE0..0xFEEF`다.
- 초기안과 달리 Attribute는 제어 bit 2를 설정하고 기존 `0x4000..0x7fff` VREG 창으로 쓴다.
- MinOS·Forth dictionary/프로그램은 I/O 16바이트를 RAM으로 사용하면 안 된다.
  새 메모리맵의 펌웨어·에뮬레이터 지원은 아직 추가하지 않았다.
- 외부 확장 카드가 같은 주소를 선택하면 충돌한다. 온보드 I/O disable 수단을 고려한다.

## 6. 배치·검증 조건

- Attribute SRAM/색상 래치는 VGA 가까이, 음원/아날로그 출력은 보드 가장자리에 배치한다.
- CPU critical path는 유지하고 신규 팬아웃의 용량·배선 길이를 평가한다.
- 각 IC에 로컬 decoupling, 음원/앰프에는 적절한 bulk capacitor와 전원 필터를 둔다.
  아날로그/디지털 접지면을 무조건 분리하지 말고 연속된 귀환 경로를 확보한다.
- 신규 참조번호는 원본 IC와 충돌하지 않는 범위로 배정한다. 원본 번호는 가능한 보존한다.
- CPU 클록, VGA_GET, SRAM WE/OE, 색상 latch clock, pixel, SN clock/WE/READY에 테스트 포인트.
- 리셋·브라운아웃·부분 실장 시 컬러/mute 상태를 검증한다.
- 수정 제어 ROM 경로/검증은 기존 `docs/HARDWARE_SHOPPING.md`를 따른다.

### 제조 전 통과해야 할 항목

1. 실제 회로도와 정확한 부품/데이터시트/풋프린트 확정.
2. 주소 decode·INH·bank·버스 방향/tri-state truth table 검증.
3. SRAM 주소 MUX→읽기→색상 latch와 카운터 전환의 worst-case setup/hold 계산.
4. 비트맵과 색상의 첫/마지막 픽셀 정렬, Attribute 행 위상, blanking 검증.
5. Attribute 쓰기 중 표시 안정성·요청 유실·최대 갱신율 검증.
6. SN 쓰기 타이밍, 데이터 bit 순서, TTL/CMOS 경계, 리셋 mute 검증.
7. 에뮬레이터/논리 모델 확장 및 기존 CPU 회귀 검사. 이것만으로 전기 검증을 대체하지 않음.
8. KiCad ERC/DRC, netlist 대조, 커넥터·패키지 치수 검사.
9. 전류 예산, VGA 75Ω 출력, 오디오 출력 부하 검토.
10. 시제품에서 오실로스코프 실측과 장시간 CPU/영상/음원 동시 동작 시험.

첫 주문은 검증용 시제품이다. 실기 시험 전 상태를 양산 검증 완료로 표시하지 않는다.

## 7. 현재 산출물과 남은 작업

- 완료: 요구사항, 참고 net 연결 검토, 좌표 보정식, 주소/인터페이스 후보 정리.
- 완료: [수정 CAD 작업본](cad/PROVENANCE.md)의 ERC·DRC·패리티 0건,
  기존 DRC 제외 항목 제거, 원본 회로 연결·동박 형상 보존 검사.
  KiCad에서는 `cad/8-Bit CPU 32k.kicad_pro`를 연다.
- 완료: 실제 통합 회로도 5개 sheet, PCB 부품·pad/net 반영, 추가 BOM 초안,
  디지털/정적 테스트 24개. [현재 상태](CIRCUIT.md)를 참고한다.
- 미완료: 추가 회로 배선, 최종 배치, 제조사 최대값 기반 타이밍 검증,
  새 장치의 에뮬레이터·펌웨어 지원 및 실기 검증.
- KiCad 10.0.7 설치 후 원본 CAD의 ERC/DRC/회로도 parity 기준 검사를 실행했다.
  결과와 재현 방법은 [KICAD_BASELINE.md](KICAD_BASELINE.md)를 참고한다.
  수정 기준 작업본도 같은 도구로 검사했다. 통합 회로도·PCB 검증이나 제조 출력이 완료된 것은 아니다.
- 원본 보드 회로도에 표기된 CC BY-NC-SA 4.0 고지와 외부 프로젝트의 권리 조건을
  파생 CAD 배포 전에 확인·보존한다. hans61 저장소의 공개 접근을 재배포 허가로
  간주하지 않는다. 라이선스 확인 전 회로 파일을 통째로 복사해 배포하지 않는다.
