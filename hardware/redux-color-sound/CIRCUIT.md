# 컬러·SN76489 통합 회로 — CS-DRAFT-1

**실제 회로도와 PCB 배치가 추가된 검토용 초안이다. 배선·최악 조건 타이밍 검증은
미완료이며 PCB 주문/제조에 사용하면 안 된다.**

KiCad에서 `integrated/8-Bit CPU 32k.kicad_pro`를 연다.
`cad/`는 이전의 경고 없는 흑백 기준 보드로 그대로 보존했다.

## 추가된 회로

| 시트 | 내용 |
| --- | --- |
| ExtensionIO | ATF22V10C 단일 단 디코더(`0xFEE0..0xFEEF`, RAM `/CE`), 제어 레지스터, 음원 데이터 래치, 쓰기 plane 선택 |
| PSG | SN76489AN, 독립 3.579545MHz 발진기, HCT 상태 버퍼, power-on reset, 하드웨어 mute, 모노 line-out |
| Attribute | 별도 AS6C62256-55PCN, 세로 주소 위상 +4, 데이터 버퍼, 색상 표시 래치, pending write plane 래치 |
| Palette | 표시 영역 판정/유지, 전경·배경 선택, 흑백 bypass, AC244 RGBI 출력 버퍼, 저항 DAC |
| ExtensionPower | IC별 100nF, 발진기 100nF, 10µF bulk capacitor |

추가 부품은 **IC 24개를 포함해 68개**다(2026-11-24 PLD 디코드와 Attribute 주소 경로 수정 반영 후). 단자·수동소자를 포함한 수량이며,
전체 보드 BOM이나 예비품 수량은 아니다. `integrated/extension-bom.csv`를 참고한다.
구매 가능한 정확한 주문번호·속도 등급·제조사별 최대값은 제조 전에 확정해야 한다.
온보드 스피커 앰프, SD, 조이스틱, TTS, 프로그래머는 추가하지 않았다.

## 최소 구성으로 바꾼 부분

초기 문서의 간접 Attribute 주소/데이터 포트 대신 **기존 영상 VREG를 공유**한다.
별도 CPU 주소 래치·주소 MUX·쓰기 대기열을 중복 추가하지 않는다.

- Attribute SRAM 열 주소(A0–A5)는 VA0–VA5를 그대로 쓴다. 행 주소(A6–A10)는 별도 `CS_CA` 버스로 받는다.
  - 표시 쪽: U78 adder와 U79 XOR가 470Ω 저항 앞의 스캔 카운터 출력(`CS_V4..V128`)에서 +4 위상 행을 계산한다.
    결과는 R37–R41(470Ω)을 거쳐 `CS_CA`로 간다. 기존 VA 버스의 저항 분리 방식과 같다.
  - CPU 쓰기 쪽: U66 HC574가 A9..A13을 U41과 같은 클록(VREG_CP)·OE로 래치해 `CS_CA`를 직접 구동한다.
  - Palette 표시 영역 판정도 저항 앞의 카운터 출력(`CS_H2..H32`, `CS_SCA7..10`)을 쓴다.
    그래서 확장 회로는 VA6–VA13에 부하를 주지 않고, VA0–VA5에는 U77 입력 하나만 더한다.
- U38의 보류된 영상 데이터를 U80으로 Attribute 데이터 버스에 전달한다.
- U82는 VREG가 쓰기를 캡처하는 시점의 plane을 저장한다. 제어 bit를 나중에
  바꾸더라도 이미 캡처한 쓰기의 목적 plane은 바뀌지 않는다.
- U36 비트맵 SRAM과 U77 Attribute SRAM의 WE를 분리해 둘에 동시에 쓰지 않는다.
- Attribute 쓰기 모드에서는 해당 CPU RAM 창을 inhibit해 기존 비트맵 RAM mirror를 보존한다.
- U70은 별도 clock gate 대신 **enable이 있는 HC377**을 사용한다.
  기존 `CLK_MAR`를 직접 사용하며 주소 디코더 출력으로 클록을 만들지 않는다.
- U79의 XOR 하나를 `RGB_BLANK` 반전기로 쓴다. PLD 도입 후 U79에는 XOR 두 개가 남는다.

`U67`, `U68`, `U73`과 각 바이패스 `C37`, `C38`, `C43`은 의도적으로 비어 있는 참조번호다.
U67·U68은 PLD 도입으로 제거되었고, U66은 Attribute 행 래치(HC574)로 다시 쓴다. 번호를 메우기 위해 부품을 추가하지 않았다.

## 주소 디코드 PLD (U64, 2026-11-24)

[TIMING_REVIEW.md](TIMING_REVIEW.md) 조건 4에 따라, 기존 HC04→HC30→HC04→HC11→HC32→HC32
6단 체인(U64 HC30, U65 일부, U66 HC138, U67/U68 HC11, U71 일부, U79 일부, U72 일부)을
**ATF22V10C 한 개**로 바꿨다. 이제 RAM `/CE`는 주소 버스에서 PLD 한 단을 거친다.

| 출력 핀 | 넷 | 식 |
| --- | --- | --- |
| 23 | `CS_RAM_INH` → U34 `/CE` | `INH_EXT + HIT + ATTR_MODE·A14·/A15` |
| 22 | `CS_STATUS_SEL_N` → U72 OR(`~RO`) → U75 OE | `/(HIT·/A2·/A1·A0)` |
| 21 | `CS_CTRL_SEL_N` → U69 E1 (E2 = `~RI`) | `/(HIT·/A2·A1·/A0)` |
| 20 | `CS_SND_EN_N` → U70 E | `/(HIT·/A2·/A1·/A0·/~RI)` |

`HIT = A15..A9 · /A8 · A7·A6·A5 · /A4`이며 A3은 디코드하지 않는다. 이는 기존에 문서화한 alias와 같다.
입력은 A0–A2, A4–A15, `ATTR_MODE`, `INH_EXT`, `~RI`로 18개, 출력은 4개다. 22개 신호 핀을 모두 쓴다.
`~RO`는 PLD 밖 U72에 남겼다. 상태 OE는 RAM `/CE` 경로가 아니다.

- **식의 단일 원본:** `extension_design.py`의 `PLD_EQUATIONS`.
  생성기가 `integrated/extension-decode.pld`(GALasm/galette 형식, GAL mode 5892 fuse)를 쓰고,
  테스트가 이 파일과 manifest, U64 핀 연결을 대조한다.
- **아직 컴파일하지 않았다.** JEDEC 생성(galette 등)과 프로그래머 기록은 별도 단계다.
  Power-down(PD) fuse를 켠 JEDEC를 쓰면 안 된다. PD를 켜면 pin 4(A7)가 PD 핀이 된다.
- **부품:** DIP 24핀 300mil. 데이터시트 주문표의 PDIP는 `-7PC`(7.5ns, 0–70°C),
  `-10PC/-10PI`, `-15PC/-15PI`다. 유통사는 무연 `-7PX`/`-10PU`도 표기한다. 구매 전에 확인한다.
- **전원:** ICC 85mA typ, 130mA max(-7/-10). 기존 HC 게이트보다 훨씬 크므로 전류 예산(조건 8)에 넣는다.

## 메모리맵과 제어

| 주소 | 동작 |
| --- | --- |
| `0xFEE0`, `0xFEE8` | 쓰기: SN76489 데이터 유지 레지스터 |
| `0xFEE1`, `0xFEE9` | 읽기: 상태, 아래 표 참고 |
| `0xFEE2`, `0xFEEA` | 쓰기: 제어 레지스터 |
| `0xFEE3..0xFEE7`, `0xFEEB..0xFEEF` | 예약. RAM도 선택되지 않는다 |

주소 bit 3은 미디코딩하여 위 alias가 생긴다. 이 영역은 CPU RAM과 겹쳐 구동하지
않도록 온보드 inhibit를 추가했다. 기존 확장 카드가 같은 주소를 디코딩하면 충돌한다.
Forth dictionary/프로그램은 이 16바이트 영역을 RAM으로 사용하면 안 된다.
펌웨어·에뮬레이터의 새 장치 드라이버/메모리 상한 처리는 이번 CAD 작업에 포함하지 않았다.
현재 `os.asm`을 네이티브 어셈블러로 확인한 kernel 끝은 `OS_Image_End=0xf9ad`여서
이 I/O 창과 겹치지 않는다. 이것이 모든 사용자 프로그램의 주소 호환성을 보증하지는 않는다.

| bit | 제어 쓰기 | 상태 읽기 |
| --- | --- | --- |
| 0 | 컬러 enable | SN READY, 1=처리 완료 |
| 1 | SN write assert, 1=CE/WE low | Attribute 쓰기 모드 |
| 2 | Attribute 쓰기 모드 | 컬러 enable |
| 3 | 오디오 unmute | 오디오 unmute |
| 4..7 | 무시 | 0 |

제어 레지스터는 공유된다. 소프트웨어에 shadow byte를 두고 다른 bit를 보존해야 한다.
리셋 시 제어는 0이다. Attribute 주소/데이터 전용 `FEE4/FEE5/FEE6` 포트는 **구현하지 않았다**.

### Attribute 갱신

1. 제어 bit 2를 설정한다.
2. `0x4000..0x7fff`에 색상 바이트를 쓴다. 행은 주소 A13..A9(= `y >> 3`)로 정해진다.
3. 마지막 보류 쓰기의 commit 시간을 확보한 뒤 bit 2를 해제한다.
4. Attribute 초기화가 끝난 뒤에만 bit 0을 설정한다.

색상 바이트는 `background[7:4] | foreground[3:0]`, 각 색상 번호는 `I:R:G:B`다.

```text
ViewPort cell: column=0..49, row=0..29
쓰기 주소 = 0x440c + row*512 + column      (cell의 아래 네 줄 중 첫 줄)
Attribute SRAM index = (row+2)*64 + column+12
```

**쓰기 경로에는 +4 위상 adder가 없다**(2026-11-24, [TIMING_REVIEW.md](TIMING_REVIEW.md) 11절).
cell의 아래 네 줄(y = 16+8·row..19+8·row)만 그 cell을 가리킨다. 위 네 줄에 쓰면 한 행 위의 Attribute가 바뀐다.
표시(스캐너) 쪽은 그대로 +4 위상을 적용하므로, cell의 8줄 모두 같은 색으로 보인다. 프로그램은 색상을
cell당 한 번만 기록하면 된다. 32KB SRAM 중 2KB만 사용하고 나머지 주소 입력은 GND다.

Attribute 모드가 켜진 동안 CPU의 `0x4000..0x7fff` **읽기도 inhibit**된다.
비트맵 RAM mirror를 읽기 전 반드시 모드를 해제한다. 이 포트는 SRAM read-back을
제공하지 않는다. 기존 VREG와 마찬가지로 단일 보류 쓰기이며 무한 FIFO가 아니다.
원본보다 빠르게 연속 쓰기를 보내도 된다고 가정하지 않는다.

### 음원 갱신

- U70에 데이터를 먼저 유지한다. TI의 D0=MSB 관례에 맞춰 bit 순서를 연결했다.
- 제어 bit 1을 설정해 SN의 CE와 WE를 함께 low로 만든다.
- READY의 assert 지연을 고려한 최소 시간을 확보한 뒤 READY high를 확인한다.
- bit 1을 해제하고 다음 바이트를 준비한다. 전송 중 U70을 덮어쓰지 않는다.
- 무음 명령 `9f bf df ff` 초기화 후 bit 3으로 unmute한다.

약 32 음원 클록은 3.579545MHz에서 약 8.94µs이지만 **보증 최대 쓰기 시간이 아니다**.
정확한 칩의 데이터시트와 실측으로 최소 strobe/유지 시간을 확정해야 한다.
READY는 CPU WAIT/클록에 연결하지 않았으며, 소프트웨어 폴링/지연에는 CPU 시간이 든다.
독립 발진기를 쓰므로 CPU 클록을 음원 주파수에 맞추지 않는다.

J6은 **외부 앰프용 모노 line-out**(1=신호, 2=GND)이다. 스피커나 헤드폰을 직접
구동하는 출력이 아니다. Q1이 부팅/리셋 중 오디오를 shunt mute한다.

## 전압·리셋·출력

- 전체 전원은 정전압 **5.0V ±5%**로 제한했다. 수정 전 보드의 5.5V 상한을 그대로 쓰지 않는다.
- U76 MCP130-450DI/TO를 추가하고 기존 R2 reset pull-up을 **470Ω→4.7kΩ**로 바꿨다.
  원래 470Ω 그대로면 supervisor의 sink 전류 조건을 벗어날 수 있다.
- 기존 R6는 RGB 공통 저항이 아니라 **red 750Ω**으로 바뀐다. R28/R29는 green/blue 750Ω,
  R30/R31/R32는 intensity 각 1.5kΩ이다. DAC 저항은 1%급 기준이다.
- 75Ω 종단, 이상적인 5V 출력에서 full-scale 약 **0.652V**. 5.25V와 저항 -1% 조합도
  0.7V 이하다. 출력단 유한 저항·부하·주파수 응답·허용오차 실측은 별도다.
- DAC 구동에는 **74AC244**를 쓴다. 원래 CPU HC 부품을 AC로 바꾼 것이 아니다.
- U81은 **74HCT377**이다. 새 SRAM의 TTL 수준 VOH와 HC 입력 임계값을 무심코 연결하지 않는다.
  READY 상태 입력도 HCT244를 사용한다.
- blanking 시 DAC 버퍼를 high-Z로 하고 모니터의 75Ω 종단으로 RGB를 0V로 만든다.
- HSYNC/VSYNC와 UART, CPU 클록 생성기·마이크로코드는 변경하지 않았다.

## 현재 검증 결과

- KiCad 10.0.7 ERC: **0건**.
- PCB physical DRC 및 schematic parity: **0건**.
- **미배선 연결 384건**(Attribute 경로 수정 후): DRC 전체 결과는 실패(종료 코드 5)다. 제외하지 않았다.
- 디지털/정적 검사 **33개 통과**(배선 채택 검사 1개 skip). 모든 CPU 주소, 전체 논리 raster의 색상 주소·blanking,
  음원 bit 순서, 두 SRAM 쓰기 plane 상호 배제, 실제 netlist의 핀 연결을 검사했다.
- 원래 회로의 연결 그룹은 의도한 인터페이스 7개 pad를 제외하면 같다.
- 기존 네트 4개의 분리가 필요해 관련 track/via **26개**를 제거했다.
  대상은 INH, VGA WE, 기존 RGB 공통선, 기존 pixel–R6 선뿐이다.
  CPU 클록/ALU/명령 경로의 기존 배선을 지운 것이 아니다.
- 새 부품 68개의 footprint와 실제 pad/net를 PCB에 반영했다.
  2026-11-25부터 새 부품은 원래 보드 위쪽에 붙인 **높이 약 112mm의 띠**에 배치한다.
  외형은 VGA 커넥터 J4 위를 비운 L자다([TIMING_REVIEW.md](TIMING_REVIEW.md) 12절).
  - 크기: 232 × 270mm, 약 58,700mm². 이전 오른쪽 shelf 배치는 422 × 158mm였다.
  - 원래 모서리 구멍 H2/H4는 이제 보드 안쪽에 있고, 새 위쪽 모서리에는 구멍이 없다.
  - 이것도 배선 전 **검토용 배치**이며, 최종 보드 크기나 구매 규격이 아니다.

## 아직 통과하지 않은 조건

> 2026-11-24 데이터시트 계산 결과는 [TIMING_REVIEW.md](TIMING_REVIEW.md)에 있다.
> 조건 4(RAM `/CE` 6단 디코드)와 2·3(Attribute 주소 adder, VA 버스 용량)은 원본 최장 경로보다 긴
> **구조적 회귀**로 판정했다. 5는 배치를 압축한 뒤 다시 계산해야 하고, 6·7은 통과다.
> 회로 수정 전에는 재배선하지 않는다.

1. 새 회로의 실제 배선 384개 연결, ground plane 확장, compact 재배치 및 제조 DRC.
2. SRAM 주소 settle/접근/출력 enable와 16MHz capture의 setup/hold 최대값.
3. VREG 캡처와 plane FF의 전환, WE 펄스 폭·non-overlap/글리치 검증.
4. 새 INH 디코더가 CPU RAM 접근의 기존 시간 여유 안에 도착하는지 확인.
5. 추가 clock fan-out·배선 부하가 8MHz/16MHz 파형을 훼손하지 않는지 확인.
6. pixel→두 mux→DAC 및 blanking 지연의 정렬. 디지털 주소 테스트가 이 지연을 보증하지 않는다.
7. READY와 실제 SN 부품/변형의 write timing, reset 중 mute, 음성 출력 레벨 검증.
8. 부품별 최악 소비전류·전원/발열·접지 귀환·실기 장시간 동시 동작 시험.

설계 방향은 **CPU 클록 저하·WAIT·DMA 없이** 처리하는 것이지만, ERC/디지털 테스트만으로
실제 8MHz 동작을 보증하지 않는다. 위 조건을 충족하지 못하면 주변 회로·배치·부품을
수정해야 하며, CPU를 느리게 해서 요구사항을 우회하지 않는다.

## 재생성 및 검사

기존 디렉터리는 덮어쓰지 않는다. 새 목적지에서만 생성한다:

```sh
python3 hardware/redux-color-sound/add_extensions.py \
  --destination hardware/redux-color-sound/build/new-integrated

/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 \
  hardware/redux-color-sound/place_extensions.py \
  --project hardware/redux-color-sound/build/new-integrated

python3 hardware/redux-color-sound/check_kicad.py \
  --source hardware/redux-color-sound/integrated \
  --out hardware/redux-color-sound/build/integrated-final --refill-zones

python3 -m unittest discover -s hardware/redux-color-sound -p 'test_*.py' -v
```

배치 스크립트도 기존 `placement-report.json`이 있으면 재실행을 거부한다.
수동 배선한 작업을 재생성 도구로 덮어쓰지 않는다. 실제 source pin manifest와
회로도 XML netlist, 추가 BOM을 함께 보관했다. 이 생성기는 논리 회로 초안을 만드는 도구이며
향후 수동 배선·제조 검증을 자동 재현한다고 주장하지 않는다.
