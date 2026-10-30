# Minimal 64x4 Redux Forth — 프로젝트 진행 상황

최종 업데이트: 2026-10-30

**현재 ROM 정책:** 수정 ROM은 `minimal64/Revision 1.4 Redux/FLASH Images/`에 직접 설치되어 있으며 이 위치를 빌드·에뮬레이터·테스트의 단일 기준으로 사용한다. 삭제된 원본 ROM이나 별도 `roms/` 번들은 필요 없다. 아래의 원본/수정본 분리·비교 기록은 과거 이력이다. 현재 검증은 수정 ROM만 실행하며 `python3 minredux/verify_rom.py`가 수정 SHA-256과 CSV 전체를 검사한다.

## 목표

- [x] Minimal 64x4 **Revision 1.4 Redux**용 고속 마이크로코드 실행 에뮬레이터 구현
- [x] 전체 ISA의 명령 수준 독립 검증 행렬 구축·실행: 공개 255개 + 내부 ff 상태, 배포 ROM 의미 불일치 3건 별도 기록 (실기 타이밍 대조·확장 포트는 범위 제외)
- [x] 에뮬레이터를 oracle로 사용해 Min보다 빠른 Forth 구현 완성
- [x] headless 자동 테스트/벤치마크
- [x] 대화형 프론트엔드 제공

## 하드웨어 정확도 개선 계획 (2026-10-29 검토 후)

기존의 부팅 및 Forth 회귀 통과는 전체 하드웨어의 사이클 정확성을 입증하지 않는다. 아래 순서로 구현과 자동 검증을 추가하며, 완료한 항목에 검증 결과를 기록한다. 부품의 아날로그 지연·발진기 오차까지 재현한다는 의미의 정확성은 주장하지 않는다.

1. [x] **UART/플래시 기능 호환성**: UART 7비트 송수신, FLASH unlock 주소의 A18..A15 don't-care, chip erase 및 software ID 모드. 각 차이에 대한 실패 재현을 자동 테스트로 고정.
2. [x] **FLASH 작업 타이밍**: 프로그램/섹터 삭제/전체 삭제의 busy 상태, DQ7 polling·DQ6 toggle, busy 중 명령 무시. SST39SF040의 대표 시간을 기본값으로 사용하되 실측 보장값과 구분.
3. [x] **CPU 결과·사이클 검증 기반**: 제어 ROM 전체와 CSV 대조, 독립적인 명령 기대값/사이클 검사, ALU·분기·페이지 경계·스택·리셋 관련 회귀 추가. 검사하지 않은 명령까지 검증 완료로 표시하지 않음.
4. [x] **프레임 단위 입력 모드 분리**: 기존 편의용 buffered 입력 유지, UART/PS2 전송 시간을 따르는 timed 입력 추가. 수신 레지스터가 차 있거나 UART 송신 중인 상황에서 무한 호스트 큐가 하드웨어 손실을 숨기지 않도록 검사.
5. [x] **VGA 디지털 모델 및 실시간 실행**: 별도 VRAM/VREG·주사 상태 모델, CPU RAM과 영상 반영 지연 분리. 선택적인 8MHz 호스트 동기화 추가. 디지털 모델의 범위와 아직 실기 비교가 필요한 부분 명시.

검증 명령: `cd minredux` 후 `cargo test`, `cargo build --release`, `python3 regress.py`. Rust 변경 후 Python 회귀 전에 release 실행 파일을 다시 빌드한다. Forth 소스를 바꾸지 않은 경우 기존 커널 이미지를 사용한다.

### 진행 기록

- 계획 등록: 위 5개 우선순위로 작업 시작. 기존 기준선은 `cargo test` 0개, Forth 회귀 33/33 통과. 검토용 별도 프로그램에서 UART 8비트 통과, FLASH 즉시 완료, unlock alias 거부, chip erase 미처리를 재현.
- 1단계 완료: UART 입출력 `& 0x7f`, FLASH 명령 주소 `& 0x7fff`, chip erase, SST 제조사/장치 ID(`bf/b7`), 두 ID 종료 방식 구현. 프로그램 데이터 `0xf0`는 종료 명령과 구분. `cargo test` 4/4 통과.
- 2단계 완료: FLASH 작업을 완료 시점까지 보류하고 프로그램 112클록, 섹터 삭제 144,000클록, chip erase 560,000클록을 기본값으로 사용. `FlashTiming`으로 조정 가능. DQ7/DQ6 polling, busy 중 쓰기 무시, CPU reset과 FLASH 작업 독립성을 검사. 데이터시트에서 busy 읽기의 유효 비트가 아닌 나머지 비트는 보장하지 않음. `cargo test` 6/6 통과.
- 3단계 검증 기반 완료: CSV와 제어 ROM 524,288항목 전수 대조; ADI/SUI/CPI/ACI/SCI의 입력 및 carry 조합 458,752개에 대해 결과·플래그·3클록 실행 확인. 8종 조건 분기(두 길이), operand-fetch 페이지, LDI/LDB/LDT/JAR, PHS/PLS 및 JPS/RTS 페이지 경계 검사 추가. 실제 RESET 배선에 맞춰 PC/MAR/BANK/SC만 초기화하고 A/B/IR/FR·RAM·I/O·경과시간은 유지하도록 수정; `set_reset`으로 reset 핀 유지 가능. MAR의 PC 복사는 같은 edge에서 갱신되기 전 PC를 사용하도록 수정(배포 ROM에는 해당 동시 갱신 조합이 없어 기존 프로그램 결과에는 영향 없음). `cargo test` 13/13, release 재빌드 후 Forth 33/33 통과. **전체 256개 명령의 독립 oracle 및 실기 파형 대조는 아직 미완료**.
- 4단계 완료: 기본 `--input-mode buffered`는 기존 lossless 호스트 도우미로 유지. `--input-mode timed`는 UART 최초 도착/후속 프레임을 각각 160클록 지연시키고, full latch 또는 송신 충돌 시 수신을 버리고 통계를 기록. PS/2는 기본 16,000클록 프레임(`--ps2-frame-cycles` 조정 가능), full latch의 후속 프레임 손실을 검사. UART 출력도 시작 시점이 아닌 160클록 송신 완료 시점에 공개. `cargo test` 17/17 통과. **이는 정상 프레임 단위 모델이며 CLK/DAT/RX 비트 파형·잘못된 프레임·중간 재동기화까지 구현한 것은 아님**.
- 5단계 구현: `minredux/src/video.rs`에 별도 16KB VRAM, 1항목 VREG, scanner 점유 시 write 지연, 4 CPU 클록/byte 및 2 pixel/CPU 클록 시프트를 추가. 회로도 Q6 미연결·V4/V256 clear에서 520 scanline/133,120 CPU 클록의 frame 및 HSYNC/VSYNC를 모델링. `text_screen`/ASCII는 CPU RAM 대신 VRAM을 읽으며, 주사 중 샘플은 `Video::scanout()`으로 별도 노출. CPU RESET은 영상 상태를 지우지 않음. `--realtime`은 run/bench/term에 선택적 8MHz host pacing 적용; 느린 호스트에서 가상 클록 생략 없음. 정확도 범위·CLI·근거 자료는 `minredux/README.md`에 정리.
- 5단계 통합 확인: Rust **25/25**, `cargo clippy --all-targets -- -D warnings`, Forth **33/33** 통과. `speed.fs`의 종료는 기존과 동일한 **3,538,944클록**, VREG overwrite=0. 원본 MinOS의 FLASH 저장 후 RAM을 지우고 파일명 자체를 명령으로 입력하여 데이터 재로드·실행을 자동 검사(MinOS에는 별도 `load` 명령이 없음). timed UART에서 연속 `dir\n` 전송 시 반이중 echo 충돌에 따른 3프레임 손실 확인(기존 lossless 동작과 의도적으로 다름). `--realtime --cycles 800000`은 가상 100ms 이상 경과 확인. 실기 절대 위상·sub-cycle 지연·전체 ISA 대조는 여전히 미완료이며 "모든 하드웨어가 엄격히 동일"하다고 주장하지 않음.

### 후속 검증 / 아직 완료하지 않은 범위

- [x] 독립 기대값 검사 범위를 나머지 ISA 명령(특히 word/long 연산·모든 간접 주소지정·WIN/OUT 상태 전이)으로 확장. 아래 전체 ISA 검증 결과 및 알려진 ROM 예외 참조.
- [ ] UART/PS2 비트 파형 및 malformed frame·중간 재동기화 모델. 현재 timed 모드의 프레임 충돌 손실 처리는 디지털 근사이며, 데이터가 실제로 어떻게 깨지는지까지 일치시키지 않음.
- 범위 제외(사용자 결정): 실기 logic-analyzer trace 및 실기 타이밍 대조. 전원 투입 위상·전파 지연은 검증 주장에 포함하지 않음.
- 범위 제외(사용자 결정): 확장 포트 INH 및 외부 메모리 매핑. Redux 기본 보드만 대상으로 함.

### 전체 ISA 검증 작업

- [x] 0x00..0xfe의 공개 명령 및 내부 0xff 상태를 구분한 누락 방지 coverage 검사.
- [x] ROM을 다시 해석하는 방식이 아닌 명령 수준 산술·메모리·주소지정 기대값과 소요 클록 대조. opcode/길이는 공식 assembler와 교차 검사.
- [x] word/long carry·borrow·early exit, 모든 간접 주소지정, 페이지·주소공간 경계, 스택 순환 및 WIN/OUT 상태 전이 검사.
- [x] 불일치 시 Rust 코어 결함과 배포 microcode 자체의 명령 의미 차이를 구분. 실기 ROM 동작을 숨기는 opcode별 에뮬레이터 보정은 하지 않음.
- 작업 시작: 실기·확장 포트 제외 범위를 반영하고 전체 ISA용 독립 semantic oracle을 추가하는 중.
- 구현 완료: `minredux/src/isa_tests/`에 arithmetic/data/control의 명령 수준 reference와 공통 검증 harness 추가. 공개 opcode **255/255**, **21,446 cases**, 누락 0개를 실제 opcode별 보고서로 확인. 0xff는 공개 명령이 아닌 OUT 내부 대기 상태로 별도 검사.
- 강화 검사: 기존 즉시 산술 458,752개 외에 즉시 논리 196,608개, word 단항 연산/shift 655,360개, word 비교 393,216개를 추가. 전체 RAM 및 FLASH, 정의된 A, FR, PC/MAR/BANK/IR, I/O latch/output, 클록을 비교하며 명령 결과로 정의되지 않은 A는 일부 long 조기 종료 경로에서 제외. mutation 검사 4개로 잘못된 A·FI·RAM write·종료 클록을 oracle이 거부하는지 확인.
- 배포 ROM 결함 1: **0x52 BXR / XR.B**는 최종 목적지 writeback이 없어 목적지가 그대로이고 scratch 00ff에 AND 중간값만 남음. 독립 의도값과 실제 차이가 나는 7 cases를 명시적으로 검사.
- 배포 ROM 결함 2: **0x54 RXR / XR.R**는 목적지 대신 scratch 00ff에 최종 XOR 값을 씀. 독립 의도값과 실제 차이가 나는 7 cases를 명시적으로 검사.
- 배포 ROM 결함 3: **WIN at ffff**에서 반복 대기 중 UART/PS2 입력 도착 시 의도된 다음 PC=0000이 아니라 ff00으로 wakeup하는 mid-instruction 제어 행 전환 문제 재현. 정상 8000/80ff wakeup과 함께 별도 검사.
- ROM 예외는 "ISA 완전 준수"로 숨기지 않고 원본의 정확한 관찰 결과를 별도 assertion으로 고정. 이번 행렬에서 추가 Rust 코어 수정은 필요하지 않았고 원본 ROM/CSV도 변경하지 않음. 상세 재현·ROM hash·검증 한계는 `minredux/ISA_VALIDATION.md`.
- 최종 검증: `cargo test` **39/39**, `cargo test --release` **39/39**, `cargo clippy --all-targets -- -D warnings`, `cargo fmt --check`, release 재빌드 후 Forth **33/33** 통과. 전체 ISA만 실행: `cd minredux` 후 `cargo test tests::isa`. opcode별 보고서: `MINREDUX_ISA_REPORT=1 cargo test all_public_opcodes -- --nocapture`.
- 판정 범위: 전체 **opcode coverage**와 위 입력 집합의 독립 검증은 완료했지만 모든 32비트 입력 조합·임의의 self-modifying/alias 조합·모든 비동기 도착 시각의 전수 증명은 아님. 사용자 요청에 따라 실기 타이밍 대조와 확장 포트는 수행하지 않음.

### 수정 ROM 제작과 참조 ROM 반영

- [x] 수정 제어 ROM 3종은 현재 `minimal64/Revision 1.4 Redux/FLASH Images/`에 직접 설치되어 있다. 에뮬레이터·벤치마크·커널 빌드·Rust 검증은 이 경로만 기본으로 사용하며, 삭제된 원본 파일이나 별도 번들은 필요 없다. `minredux/verify_rom.py`로 현재 수정 hash와 CSV 재현성을 확인한다.
- [x] 재현 가능한 생성 도구에 원본 hash 확인·원본 경로 쓰기 금지·기존 다른 내용 덮어쓰기 방지 추가.
- [x] XR.B/XR.R의 MAR을 목적지에 유지하여 in-place AND/OR/XOR writeback 구현. 기존 10/13클록 유지.
- [x] WIN 대기 경로의 FI를 low-byte 감소 시점으로 늦춰 중간 ready-row 전환 시 잘못된 high-byte 감소 방지.
- [x] 원본 결함 회귀는 유지하면서 수정본에도 255개 전체 ISA 행렬, XOR 전수 검사 및 다양한 입력 도착 시각의 WIN 검사를 적용.
- 이어서 완료 확인(2026-10-29): 생성 도구 `--check`로 원본 hash·CSV 재조립·수정 산출물 재현성 확인. 변경은 208개 제어 워드(LSB 16바이트, MSB 0바이트, HSB 192바이트)이며 원본 및 기본 ROM 선택은 유지.
- 수정본 검증: 예외 없는 **255/255 opcode, 21,446 cases**, XR.B/XR.R **131,072개** A/메모리 조합 및 scratch 목적지 검사, WIN **4,608개** 주소·레지스터·UART/PS2 도착 시점 조합, 원본 MinOS 부팅 통과. Rust debug/release 각각 **45/45**, `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` 통과.
- Forth 통합: 기존 `minforth/build/flash.bin`을 유지하고 `minforth/build-isa-fixes-v1/`에 별도 번들 생성. release 실행 파일 재빌드 후 원본 및 수정본의 `regress.py` 각각 **33/33** 통과. 실행은 `cd minredux` 후 `./target/release/minredux term --rom-dir ../minforth/build-isa-fixes-v1 --realtime`. 실기 사용 안전성·실기 타이밍까지 인증한 것은 아님.

### 원본 프로젝트 PR 제출 (2026-10-30)

- [x] 최신 upstream `main` 확인: `1a59c95695d1a6a6147584465ee87803fe9387da`, 기존 검증 원본과 동일하며 결함 3건 유지.
- [x] 사용자 포크에 독립 브랜치 2개 푸시 후 upstream PR 생성:
  - **[PR #60 — XR.B / XR.R destination writeback](https://github.com/slu4coder/Minimal-64x4-Home-Computer/pull/60)**, `fix/redux-xor-writeback`, `6cfbb1f`.
  - **[PR #61 — WIN readiness / PC rewind](https://github.com/slu4coder/Minimal-64x4-Home-Computer/pull/61)**, `fix/redux-win-wraparound`, `0ecb4a1`.
- 두 PR은 각각 원본 main에서 분기하여 상호 의존 없음. XOR HSB 192바이트 / WIN LSB 16바이트만 변경, 각 CSV 정의 2줄 수정. 변경 없는 MinOS FLASH·매핑·MSB·Revision 1.1·Forth·벤치마크·Rust 에뮬레이터는 PR에 포함하지 않음.
- 각 PR에 표준 Python만 필요한 ROM 재생성/대상 명령 회귀, 작은 MinOS 어셈블리 재현 프로그램, 영문 원인·호환성·실기 미검증 설명 포함. 독립 portable 검사 XOR 4개 / WIN 3개 통과; 원본에 적용하면 예상한 의미 오류로 실패.
- production Rust core에서도 PR별 **255 opcode / 21,446 cases**와 XOR **131,072조합** 또는 WIN **4,608조합** 및 MinOS 부팅 통과. WIN 단독 PR은 미수정 XOR 결함의 기존 명시적 assertion을 유지. 네이티브 어셈블리 재현도 원본 FAIL / 해당 수정본 PASS 확인.
- 두 커밋의 충돌 없는 병합 결과가 기존 통합 수정 제어 ROM 3종과 바이트 단위로 동일함을 확인. 제출 직후 두 PR 모두 OPEN / MERGEABLE, CI 체크는 보고되지 않음. 실기 검증·maintainer 승인·병합 완료를 뜻하지 않음.
- 원본 `minimal64/`의 파일과 main은 그대로 유지. 별도 작업 공간은 `upstream-pr/xor/`, `upstream-pr/win/`; 브랜치는 사용자 `fork` remote를 추적함. 제출 본문·검증 명령·상세 기록은 **`upstream-pr/README.md`**.
- 로컬 재검증용 `minredux/src/isa_tests/upstream_pr.rs`(명시 실행하는 ignored 테스트) 및 `minredux/examples/rom_smoke.rs` 추가. 기본 Rust 검사 45 통과 + 1 기본 제외, opt-in 검사는 두 PR 각각 별도 통과, Clippy·포맷 통과.

## 1. 에뮬레이터 (`minredux`)

- [x] Rust로 마이크로코드 수준 CPU 에뮬레이션 구현 (검증 범위 및 한계는 위 개선 기록 참조)
- [x] Redux `flash.bin` + `ctrl_lsb/msb/hsb.bin` 로드
- [x] 컨트롤 ROM 24-bit 논리 워드로 사전 디코드 (XOR `0xEBFAF9`)
- [x] 64KB RAM / 512KB FLASH 뱅크 매핑 구현
- [x] 미연결 시스템 버스 기본값 `0xFF` 처리
- [x] Redux 플래그 `R K T N C ZH ZL` 구현 (동등 비교는 `ZL`+`ZH`)
- [x] UART 입력/출력 구현
- [x] PS/2 키보드 입력 구현
- [x] FLASH 쓰기 상태머신 구현
- [x] 50x30 텍스트 VRAM 렌더링 (`0x430c + row*512 + col`)
- [x] MinOS 2 부팅 검증 (ANSI clear + `READY.`)
- [x] 스플래시/로고 렌더링 검증 (VRAM `0x468f` = flash 로고 `0x0f00`)
- [x] 외부 Rust 의존성 0개 유지

### Headless CLI

- [x] `--dump`
- [x] `--dump-mem A:L`
- [x] `--dump-ram FILE`
- [x] `--profile`
- [x] `--trace N`
- [x] `--skip N`
- [x] `--ascii`
- [x] `--crop`
- [x] `--text`
- [x] `--until-text`
- [x] `--poll`
- [x] `--uart-log`
- [x] `--uart-after` (부팅 배너 이후 입력 주입)
- [x] 트레이스에 `a=` / `b=` 레지스터 출력 추가

## 2. MinOS / 원본 분석

- [x] flash 파일시스템 추출
- [x] `speed.min` 소스 추출 (flash `0x0d0cc`, 319 bytes)
      - 벤치마크 구조: `x<50`, 내부 `y<50`, `z<50`, `break` 포함
- [x] slu4 `asm.cpp`를 clang++로 빌드 (`minforth/tools/asm`)
- [x] 원본 `flash.bin`을 바이트 단위로 재현 가능
- [x] ISA 동작 확정 (opcode/operand 순서, carry/flags, `JPS`/`JAS`/`RTS`/`LDS`/`PHS`/`PLS`)
- [x] Min 기준선 측정: `speed.min` = **210M cycles**

## 3. Forth 툴체인

- [x] `tools/build.py` — 전처리 + 어셈블 + flash 삽입
- [x] `tools/hex2bin.py`
- [x] `tools/fspatch.py` — flash 파일시스템 삽입/교체
- [x] MinOS 프롬프트에서 hello world 엔드투엔드 동작
- [x] `minredux/runline.py` — 여러 줄 Forth 입력 후 텍스트 화면 출력 헬퍼

## 4. Forth 커널 (`forth/kernel.fs`)

### 기반

- [x] 서브루틴 스레드 방식 (본문 = `JPS` 시퀀스, `EXIT` = `RTS`)
- [x] 리터럴 인라인 푸시 (13 bytes)
- [x] 커널 로드 주소 `0x1000`
- [x] 사전 시작 주소 `0x8000`
- [x] 데이터 스택 `0x3000/0x3100`, `SP` ZP, 초기 `0xFE`, 128-cell circular
- [x] 리턴 스택 = 하드웨어 스택 (`0xff00+SP`), `MIB 0xfe,0xffff`로 초기화
- [x] 사전 헤더 레이아웃 `[len|imm][link_lo][link_hi][xt_lo][xt_hi][name...]`
- [x] 원시 단어 테이블 `[len|imm][xt_lo][xt_hi][name...]`
- [x] 토크나이저 커서를 private ZP `zIVEC`로 분리
- [x] `CLZ`(1 byte clear) / `CLV`(16-bit clear) 구분 정리
- [x] `JPS`는 A 파괴 → A 보존이 필요하면 `JAS` 사용
- [x] `nf_cbyte`, `nf_cspush` 호출을 `JAS`로 수정
- [x] `nf_cbyte`에서 A를 `zTMP2`에 보존
- [x] `INCW` 매크로로 16-bit 포인터 page crossing 처리
- [x] `nf_runxt` 수동 리턴 주소 push 수정
- [x] `primtab` 레이아웃/길이 정리

### 기본 단어

- [x] `DUP DROP SWAP OVER ROT NIP`
- [x] `+ - AND OR XOR INVERT NEGATE`
- [x] `1+ 1- 2* 2/`
- [x] `*` — 16-bit shift/add 곱셈 (`300 200 * .` → `60000`)
- [x] `/` / `MOD` — restoring long division (몫 `zNUM`, 나머지 `zNUM2`)
      (`1000 300 / . 1000 300 MOD .` → `3 100`)
- [x] `= <> < > <= >= 0= 0<`
- [x] `@ ! C@ C! +!`
- [x] `>R R> R@` (LDS 오프셋 수정 완료)
- [x] `EXECUTE`
- [x] `EMIT CR SPACE TYPE .`
- [x] `VARIABLE CONSTANT`
- [x] `BASE HERE` (ZP 주소 push)
- [x] `HEX` / `DECIMAL` 및 `BASE` 기반 `.` 출력 (2..36진)
- [x] 다중 토큰 인터프리터 (`1 2 . .` → `2 1`)
- [x] 회귀 테스트 스위트 `minredux/regress.py` (33/33 통과)
- [x] `."` — 인라인 문자열 컴파일/실행
      (JPS `wDOTQRT` + 길이 바이트 + 문자열, RTS는 `string_end-2`로 복귀)
- [x] 16-bit 숫자 파서 누락 수정 (`npf_mul`의 `SDZ zNUM2+1`)

### 출력 / 문자열

- [x] `."` (컴파일 전용, 중첩 루프 안에서도 동작)
- [x] `ABORT"` (컴파일 전용, 조건부 메시지·스택/루프/컴파일 복구·미완성 정의 롤백)

### 컴파일 / 제어 흐름

- [x] `:` ... `;` colon 정의 컴파일/실행
- [x] `IF ELSE THEN`
- [x] `wELSE` 분기 타깃 수정 — false 분기는 `JPA` 3바이트를 건너뛰고
      else 본문 첫 바이트로 가야 함 (`JPA operand + 2`)
      - 이전에는 `JPA operand`를 가리켜 false 경로가 operand 바이트를
        명령으로 실행했고, 우연히 무해한 opcode일 때만 동작했음
      - 커널이 커지면서 operand low byte가 `0x5d`(분기)가 되어 재부팅 발생
      - `THEN`은 계속 `JPA` operand를 패치, `IF`의 `BEQ`는 else 본문을 패치
- [x] `IF/ELSE/THEN` 중첩, `DO ... LOOP` 내부 ELSE,
      `BEGIN ... WHILE ... REPEAT` 내부 ELSE 회귀 테스트 추가
- [x] `BEGIN UNTIL`
- [x] `BEGIN WHILE REPEAT`
- [x] `AGAIN`
- [x] `EXIT`
- [x] `IMMEDIATE`
- [x] `wIFRT` 플래그 보존 수정
- [x] `DO` / `LOOP` 런타임 (`wDORUN`, `nf_lpop`; `LOOP`는 인라인 컴파일)
- [x] 루프 프레임을 `0x2800` RAM 스택에 연결 리스트로 구현
- [x] 가장 안쪽 루프의 index/limit를 ZP(`zCIDX`/`zCLIM`)에 캐시
      (`DO`에서 바깥 루프 인덱스를 프레임에 flush, 종료 시 복원)
- [x] 프레임 3회 순회 → ZP 캐시 비교로 단축 (약 145 → 72 cycles/iter)
      이후 `LOOP` 자체를 인라인 컴파일해 약 29 cycles/iter로 추가 단축
- [x] `I`
- [x] `LEAVE` (패치 리스트 `zLVSTK`, 루프별 base 추적)
- [x] `UNLOOP`
- [x] 중첩 루프 동작 확인
- [x] `J` (바깥 루프 인덱스)
- [x] `WORDS` — 헤더 길이 바이트를 이름 시작이 아니라 헤더 시작에서 읽도록 수정
- [x] `LEAVE` / `UNLOOP` 테스트 통과
- [x] 16-bit 루프 경계 테스트 (`300`회 합 `44850`, index `250..259` 교차)
- [x] `LOOP` 테스트를 호출 대신 인라인 컴파일로 전환
      (`LDZ/ADI/SDZ` + `ACI` carry, `CPZ` 두 바이트 비교, `BNE` back-edge)
      - `JPS wLOOPRT`/`RTS` 왕복 제거 (약 72 → 29 cycles/iter)
      - 종료 시에만 `JPS nf_lpop`으로 프레임 해제

### 미구현 / 개선 예정

우선순위 검토(2026-10-29): 현재 목표인 **정확성을 유지한 고속 Forth** 기준의 권고 순서다. 중요도는 기능·성능에 대한 영향, 우선순위는 측정 기반·의존성·위험까지 반영한 착수 순서다. P1=다음 작업, P2=후속 개선, P3=측정 후 선택이며 현재 확인된 긴급 수정(P0)은 없다. 아래 기대 효과는 아직 측정하지 않은 가설이다.

| 권고 순서 | 우선순위 | 중요도 | 항목 | 판단 근거 / 완료 조건 |
| --- | --- | --- | --- | --- |
| 1 | P1 | 높음 | 벤치마크 하네스 정리 — 완료 | 실제 함수 경계로 부팅·입력·로드·토큰화/컴파일·실행 분리, 코드 크기·메모리 high-water, 진단 4종·자동 전후 비교·계측 무영향 검사 구현. `benchmark.md`의 v2 규격 참조. |
| 2 | P1 | 높음 | `ABORT"` — 완료 | 참/거짓·메시지·전체 스택/루프 복구·현재 줄 폐기·미완성 colon 정의 롤백을 구현하고 전용 13개 회귀로 검증. BASE·완료된 사전·변수 보존. |
| 3 | P2 | 높음 | tail-call `JPA` 최적화 | 안전하게 적용할 수 있는 마지막 호출에서 `JPS`/`RTS` 왕복 제거. 단순 끝 바이트 패치 금지: 제어 흐름, 인라인 데이터, 리턴 스택 사용을 구분하여 증명 가능한 경우만 적용. 효과와 코드 크기 확인. |
| 4 | P2 | 높음 | 스택 인덱싱 비용 절감 | 여러 원시 단어의 공통 비용을 줄일 가능성이 있음. 먼저 프로파일로 비중 확인. split-byte 스택 및 순환 경계를 유지하고 산술·메모리·중첩 호출 회귀 검사. |
| 5 | P2 | 중간 | 핫 패스 원시 단어 인라인화 | 자주 호출되는 짧은 단어만 선별. 호출 제거 이득과 사전 메모리 증가를 함께 측정하며 분기 패치·`EXECUTE`·리턴 스택 의미를 유지. |
| 6 | P3 | 중간 | `nf_parse`의 반복 덧셈 곱셈 → shift/add | 입력·컴파일 시간 개선이며 이미 컴파일된 루프에는 영향 없음. BASE 2..36 및 16비트 wrap 결과를 유지하고 파싱 단독 비용으로 판단. |
| 7 | P3 | 낮음 | `DO` 인라인 컴파일 | 절감은 루프 반복마다가 아니라 진입마다 발생. 이미 LOOP가 인라인이므로 우선 낮게 둠. 짧은 루프를 자주 진입하는 측정에서 이득이 클 때 진행하고 중첩 캐시·`J`·`LEAVE`·`UNLOOP` 유지. |
| 8 | P3 | 낮음 | 상수 중복 제거 | 주로 코드 크기 개선 후보이며 대상(리터럴/상수 정의)과 변환 규칙부터 명확히 해야 함. 간접 참조 비용 때문에 느려질 수 있으므로 실제 중복량·속도·사전 크기 측정 후 결정. |

- [x] [P1 / 순서 2] `ABORT"` — 구현 및 수정 ROM 회귀 13/13 통과
- [ ] [P2 / 순서 3] tail-call `JPA` 최적화
- [ ] [P2 / 순서 4] 스택 인덱싱 비용 절감
- [ ] [P2 / 순서 5] 핫 패스 원시 단어 인라인화
- [ ] [P3 / 순서 6] `nf_parse`의 반복 덧셈 곱셈 → shift/add 최적화
- [ ] [P3 / 순서 7] `DO` 인라인 컴파일 (현재 `JPS wDORUN` 호출 오버헤드)
- [ ] [P3 / 순서 8] 상수 중복 제거

공통 완료 조건: 커널 재빌드 후 Forth 회귀 통과, 추가한 기능/경계 회귀 통과. 최적화는 동일 입력·동일 **수정 ROM**에서 전후 클록과 생성 코드 크기를 비교한다. 원본 ROM은 더 이상 실행하지 않는다. 기능 안전성을 희생하는 최적화는 채택하지 않는다.

## 5. 벤치마크 / 성능

- [x] `speed.min` 소스가 실제로는 319 bytes로 완전함을 확인
      (`min speed.min`으로 실행하는 인터프리터 방식)
- [x] Min 기준선 측정: `min speed.min` = **209,584,128 cycles**
- [x] 동등한 24 dots + 50x50 중첩 루프를 Forth로 포팅
      (`minforth/test/speed.fs`, `minredux/runfs.py`로 자동 실행)
- [x] Forth 측정 (루프 최적화 전): **13,041,664 cycles** (16.07x)
- [x] 루프 런타임 최적화 후 재측정: **6,225,920 cycles** (33.67x)
- [x] `LOOP` 인라인 컴파일 후 재측정: **3,538,944 cycles**
- [x] **Min 대비 약 59.22배 빠름 확인**
- [x] 빈 루프 기준 비용 측정: 약 72 cycles/iter (인라인 후 약 29 cycles/iter)
- [x] [P1 / 순서 1] 벤치마크 하네스 정리 — v2 단계별 클록·코드 크기·메모리 high-water·진단 4종·자동 diff·계측 무영향 검사 완료 (`benchmark.md`)

### P1 완료 기록 (2026-10-30, 수정 ROM 기준)

- **ABORT-quote**: 컴파일 전용 immediate 단어, `( flag -- )`. 0이면 inline 문자열을 넘기고 계속 실행. 비제로이면 메시지/개행 출력 후 현재 줄과 전체 caller frame을 폐기하고 REPL로 복귀. 데이터/하드웨어 SP=fe, 루프 스택=2800, loop cache·compiler/control/LEAVE 깊이 초기화. BASE·완료된 정의·변수 보존. 컴파일 중 abort 시 `26c0..26c3`의 HERE/LATEST checkpoint로 미완성 정의를 롤백. 빈 문자열·high-byte-only flag·page-crossing string·중첩 반환/루프·미완성 IF/DO/LEAVE를 포함한 **13/13** 전용 검사 통과. 사용법은 `minforth/README.md`.
- **하네스 v2**: 실제 실행 바이트와 대조한 Min/MinOS/Forth 심볼 및 JPS 복귀 PC/SP로 단계를 추적. `phases` 합은 RESET부터 end hook까지와 일치하고 execute는 기존 raw 클록과 일치. Forth compile은 입력 대기를 제외한 실제 토큰 처리/lookup/parse/emit, Min은 Tokenizer 구간을 별도로 측정. 부품별 함수 비용은 포괄값이므로 단계 합과 구별한다.
- **메모리/크기**: native runtime bytes, Forth boot/소스 사전 증가량, Min resident source/token bytes, 실제 RI 주소의 call/variable/temp/workspace span, 데이터/루프/하드웨어 스택 peak 기록. span/peak를 전체 live memory 총량으로 오해하지 않도록 규격 명시. 재귀 Fib(6)의 Min hardware stack peak는 234 bytes.
- **진단/비교**: `micro-call`, `micro-stack`, `micro-do`, `micro-parse` 4종 추가. `benchmarks/compare.py` 및 `--baseline`은 PASS·동일 ROM/입력/파라미터/정답에서만 클록·코드 크기·단계별 비용을 비교한다. 기존 7종의 실행 클록은 수정본 v1 기준 대비 **모두 0.000% 변화**, 새 ABORT primitive header로 총 사전은 11 bytes 증가.
- 수정 ROM에서 7종+empty+진단4종 × Min/Forth × 2회 = **48개** 계측 결과가 정답·스택·클록·단계·메모리 반복 재현성을 통과. 각 케이스를 계측 없이 한 번 더 실행한 **24개** 결과도 클록·전체 64KiB RAM 동일. 산출물: `benchmarks/results/p1-fixed-final-v2/results.json`. 현재 primary 경로로 전환한 뒤 `empty`/`micro-parse`의 추가 대조도 동일함을 확인 (`p1-primary-path-v2`).
- **현재 단일 ROM 경로 정리**: 빌드·CLI·벤치마크·Rust tests 모두 `minimal64/Revision 1.4 Redux/FLASH Images/`의 수정본을 사용. CSV도 수정본에 맞추고 활성 CSV/ROM 검사는 예외 없이 524,288워드 완전 일치를 요구. `verify_rom.py`는 수정본 hash까지 pin하며 삭제된 원본/생성 번들에 의존하지 않음. 원본 결함을 정답으로 삼던 WIN/XOR 예외는 활성 oracle에서 제거.
- 현재 `minforth/build/`를 **4,743 bytes** 커널과 수정 제어 ROM으로 재빌드. 기존 Forth **39/39**, ABORT 전용 **13/13**, host 하네스 **17/17**, Rust core **45 통과 + opt-in 1 제외**, observer unit **4/4** 통과. 이전 4,472-byte 커널 대비 +271 bytes. P2/P3 최적화는 아직 수행하지 않음.

### Min vs Forth 비교 스위트 (2026-10-29)

- [x] 1단계: Sieve·Bubble sort·Matrix multiply·재귀 Fibonacci와 empty 측정 프로토콜 구현.
- [x] 2단계: CRC-16/MODBUS·겹침 허용 byte search 추가, 총 6종.
- [x] 3단계: signed 16비트 중간값 범위를 보장하는 scale=32 고정소수점 Mandelbrot 추가, 총 7종.
- 실행: 루트에서 `python3 benchmarks/run.py --stage 3` (앞 단계만 실행하려면 `--stage 1` 또는 `--stage 2`). 진행 기록·규격·결과·사용법은 **`benchmark.md`**, 소스 생성/독립 reference는 `benchmarks/cases.py`, 격리 빌드/결과 저장은 `benchmarks/run.py`, CPU 클록별 hook 관찰은 `minredux/examples/benchmark.rs`.
- 측정은 화면 polling이 아닌 공통 RTS hook의 명령 진입 경계 간 raw 클록. 부팅·입력·토큰화/컴파일·사전 입력 준비는 분리하지만 hook dispatch 및 알고리즘 자체 workspace 초기화 비용은 포함. 순수 컴파일 시간이나 전체 메모리 사용량을 측정했다고 주장하지 않음.
- 원본/수정 제어 ROM 각각에서 7종+empty × Min/Forth × 2회 = **64회** 정답·스택/루프 상태·클록 재현성 통과. 동일한 작업별 배율 **2.125~9.954배**. 기존 speed의 59.22배를 언어 전체 성능으로 일반화하지 않음.
- 스위트가 드러낸 커널 선행 결함 수정: `!`/`C!`/`+!`의 한 셀 잔류, `*`의 피연산자 잔류, `/`/`MOD`의 stale `zNP` 의존. 하위 스택 셀 보존 회귀 6건 추가. 격리 빌드의 원본·수정 ROM에서 Forth 각각 **39/39**, host 계약/오류 검출 **10/10**, Rust **45/45**, Clippy·포맷 통과.
- 기존 원본 ROM과 기존 Forth 이미지 디렉터리는 덮어쓰지 않음. 하네스는 매번 현재 커널을 격리 빌드함. 이전 Forth 이미지로 새 회귀를 실행하려면 먼저 재빌드할 것.

### 벤치마크 결과 요약

| 구현 | cycles | 비고 |
| --- | ---: | --- |
| Min (`min speed.min`) | 209,584,128 | MinOS 2 인터프리터 |
| Forth (`speed.fs`, 초기) | 13,041,664 | 컴파일 + 실행 포함 |
| Forth (`speed.fs`, 루프 캐시) | 6,225,920 | ZP index/limit 캐시 |
| Forth (`speed.fs`, LOOP 인라인) | **3,538,944** | 최종 |
| 배율 | **59.22x** | Forth 우세 |

## 6. 프론트엔드

- [x] `minredux term` — 대화형 터미널 프론트엔드
      - 50x30 텍스트 VRAM을 ANSI로 렌더링, 변경된 행만 다시 그림
      - 호스트 stdin을 raw 모드(`stty`)로 전환해 UART로 전달
      - 커서 위치를 `_XPos`/`_YPos`(ZP `0xc0`/`0xc1`)에서 읽어 표시
      - 부팅 배너 이전 입력은 `uart_after = 200000`으로 지연
      - **Ctrl-]** 로 종료, 종료 시 터미널 설정/커서 복구
      - 파이프 입력(비 TTY)에서도 동작하며 EOF 후 1초 쿨다운 뒤 종료
- [x] 실제 PTY에서 검증: raw 모드/에코 off 진입, Ctrl-] 종료 코드 0, termios 복원 확인
      - `Command::output()`은 자식 stdin을 null로 주므로 `stty`에는
        `Stdio::inherit()`를 명시해야 함
- [x] `text_screen()` 글리프 역매핑 개선
      - MinOS 블록 커서(문자 코드 160)를 공백으로 처리
      - 기존에는 미인식 글리프를 `?`로 출력해 입력 대기 중 `3 ?`처럼 보였음
- [x] headless 회귀 테스트에 "화면에 `?`가 없어야 함" 검사 추가

사용 예:

```sh
cd minredux
cargo build --release
./target/release/minredux term --rom-dir ../minforth/build
```

## 현재 상태 메모

- 현재 커널 빌드: `4743` bytes at `0x1000`, `minforth/build/`에 수정 제어 ROM과 함께 갱신 완료
- 회귀 테스트: 기존 Forth **39/39** + ABORT 전용 **13/13** 통과 (수정 ROM만 실행)
- 최종 점검: 현재 primary 경로의 수정 ROM/CSV hash 일치, 기본 CLI MinOS `READY.` 부팅, Rust **49 통과 + opt-in 1 제외**, host **17/17**, Clippy·포맷 통과. P1 미완료 체크박스 0개.
- 사전 HERE는 `0x8000`에서 증가
- DO/LOOP 테스트: `: t 0 10 0 DO I + LOOP . ; t` → `45` 확인
- 중첩 루프 + `J`: `: n 0 3 0 DO 3 0 DO I J + + LOOP LOOP . ; n` → `18` 확인
- `LEAVE` / `UNLOOP` / `WORDS` / `."` / `HEX` / `DECIMAL` 정상 동작
- `."` 디버깅 교훈: JPS가 push하는 값은 `inline_start-2`이고 RTS가 +2 한다.
  `nf_cbyte`는 `zPTR`을 덮어쓰므로 인라인 길이 주소는 `zPTR2`에 보관해야 한다.
- 숫자 파싱 교훈: 16-bit 누산 시 high byte store(`SDZ zNUM2+1`)를 빠뜨리면
  `4660`이 `52`처럼 low byte만 남는다.
- `ELSE` 디버깅 교훈: 컴파일된 `IF/ELSE` 레이아웃은
  `BEQ L1 / then / JPA L2 / L1: else / L2:` 이다.
  `BEQ` 타깃은 `JPA` opcode가 아니라 **`JPA` operand + 2**(else 본문 시작)이고,
  `THEN`은 `JPA` operand를 `L2`로 패치한다. 타깃이 1~2바이트 어긋나도
  operand 바이트가 우연히 무해한 opcode면 통과할 수 있으므로,
  주소가 바뀐 뒤에야 드러나는 버그가 된다.
- 루프 캐시 주의점: 바깥 루프 인덱스는 안쪽 `DO` 진입 시 프레임에 flush해야
  `J`가 최신 값을 읽는다. 루프 종료(`nf_lpop`) 시 바깥 캐시를 복원한다.
- 커서/에러 표시 주의점: 화면의 `?`는 대부분 `nfw_err`가 아니라
  MinOS 블록 커서(160)를 글리프 디코더가 미인식해서 생긴 것일 수 있다.
  VM 상태를 덤프해 `zTOK`/`zIVEC`가 비어 있는지 먼저 확인할 것.
- `--until-text` 주의점: 입력 줄이 화면 폭(50열)을 넘으면 긴 줄이 줄바꿈되어
  `END` 같은 문자열이 두 행에 걸쳐 나타나므로 검출에 실패할 수 있다.
  이는 커널 정지가 아니라 하네스 문제이므로 `--text`로 실제 화면을 확인할 것.
- `speed.fs` 실행 결과: `SPEED TEST:........................END`
- 현재 headless 실행 예:
  `cd minredux && python3 runfs.py ../minforth/test/speed.fs --cycles 40000000 --no-output --until-text END`
