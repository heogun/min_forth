# minredux

Minimal 64x4 Revision 1.4 Redux의 제어 ROM을 실행하는 Rust 디지털 에뮬레이터. 외부 crate 의존성은 없다. Rust edition 2024를 지원하는 도구 체인이 필요하다.

## 빌드·검증

이 디렉터리에서 실행한다.

```sh
cargo test
cargo build --release
python3 regress.py
```

`cargo test`는 CPU·주변장치 검사이며, `regress.py`는 `../minforth/build`의 기존 Forth 커널 이미지를 사용하는 별도의 화면 출력 회귀다. Python 도우미는 release 실행 파일을 자동으로 재빌드하지 않는다. 커널 재빌드 명령은 상위 `AGENTS.md`를 참고한다.

전체 ISA만 검사하려면 `cargo test tests::isa`. opcode별 보고서는 `MINREDUX_ISA_REPORT=1 cargo test all_public_opcodes -- --nocapture`. 검증 범위·원본 ROM 결함·식별 hash는 [ISA_VALIDATION.md](ISA_VALIDATION.md)를 참고한다.

결함 3건을 수정한 제어 ROM은 `../minimal64/Revision 1.4 Redux/FLASH Images/`에 그대로 반영되어 있다. 별도 수정 ROM 디렉터리를 선택할 필요가 없으며, 위 검사와 실행은 이 이미지를 기본으로 사용한다.

## 실행 모드

```sh
# 원본 MinOS: 기본 ROM 경로는 현재 작업 디렉터리 기준
./target/release/minredux run --cycles 400000 --no-output --text --stats

# Forth 이미지로 대화형 실행; Ctrl-]로 종료
./target/release/minredux term --rom-dir ../minforth/build --realtime

# 외부 송신자가 프레임을 연속 전송하는 경우의 지연·손실 검사
./target/release/minredux run --input-mode timed --uart-after 200000 \
  --uart-hex 6469720a --cycles 2000000 --no-output --text --stats
```

- 기본 `--input-mode buffered`: 수신 레지스터가 비면 대기 중인 바이트를 넣는 lossless 테스트 도우미. 물리적인 통신선이 아니다.
- `--input-mode timed`: UART 프레임마다 160 CPU 클록(500kbps, 1 start + 7 data + 2 stop), PS/2 프레임마다 기본 16,000클록을 소모한다. full latch 또는 UART 반이중 송신 충돌 시 프레임을 버린다. PS/2 속도는 장치마다 다르므로 `--ps2-frame-cycles N`으로 조정한다. 호스트는 UART를 전송하기 시작할 시점에 큐를 채우며, `--uart-after`는 최초 전송 시작을 지연한다. RTS를 따르는 호스트를 흉내 내려면 buffered를 사용한다.
- `--realtime`: 기본 최대 속도 실행 대신 초당 8,000,000 CPU 클록에 맞춰 호스트를 대기시킨다. 느린 호스트에서는 클록을 생략하지 않으므로 실시간보다 느릴 수 있다. OS 스케줄링 지연까지 보장하지는 않는다.
- `--stats`: 입력 손실, VGA 프레임/VREG 덮어쓰기, 남은 FLASH busy 클록을 표시한다. `--no-output`은 UART 출력 수집만 끄며 송신 대기는 그대로 실행한다.

## 정확도 범위

- CPU는 Redux 제어 ROM을 1클록씩 실행한다. 공개 opcode 255개 모두의 결과·플래그·RAM 부수효과·클록을 독립적인 명령 수준 기대값으로 검사하고, 내부 0xff 대기 상태도 별도로 검사한다. 배포 ROM의 `XR.B`/`XR.R` writeback 및 WIN ffff wakeup 결함은 명시적인 예외 검사로 기록하며 원본 동작을 보존한다. 전체 상태 공간의 전수 증명이나 실기 타이밍 검증을 의미하지 않는다.
- FLASH는 SST39SF040 unlock alias, byte program, sector/chip erase, software ID, DQ7/DQ6 busy polling을 모델링한다. `FlashTiming`의 기본값은 데이터시트의 **대표값**인 프로그램 14µs, 섹터 삭제 18ms, 전체 삭제 70ms에 해당한다. 실제 부품의 작업 시간은 달라질 수 있다. busy 중 유효 상태 비트 외 읽기 값은 보장하지 않는다. 에뮬레이션 중 FLASH 변경은 메모리에만 남고 원본 이미지 파일을 덮어쓰지 않는다.
- `video::Video`는 별도 16KB VRAM, 단일 VREG, 4 CPU 클록마다의 바이트 fetch, 16MHz 픽셀 시프트 및 동기 신호를 모델링한다. Redux 회로의 Q6 미연결 및 V4/V256 reset에서 520 scanline, 프레임당 133,120 CPU 클록을 계산한다. `vram()`은 영상 메모리, `scanout()`은 주사 시점에 실제 읽은 바이트다. 텍스트/ASCII 프론트엔드는 VRAM 스냅샷을 표시하며 CRT 영상 파형을 렌더링하지는 않는다.
- `reset()`은 CPU RESET에 연결된 PC/MAR/BANK/SC만 초기화한다. 다른 레지스터·RAM·영상·통신·진행 중 FLASH 작업·클록 수는 유지한다. `set_reset(bool)`은 핀을 클록 경계에 걸쳐 유지할 수 있다. 최초 RAM/VRAM은 재현성을 위해 0으로 시작하며 실기 전원 투입 시의 미정값을 재현하지 않는다.
- UART/PS2는 정상 **프레임 단위** 모델이다. 비트별 외부 파형, 잘못된 프레임, 중간 재동기화 및 전압·전파 지연은 구현하지 않았다. 실기 타이밍 대조와 확장 포트(INH/외부 메모리 매핑)는 사용자 결정으로 프로젝트 범위에서 제외한다. VGA의 절대 전원 투입 위상과 sub-cycle 지연의 실측 일치는 주장하지 않는다.

근거: `../minimal64/Revision 1.4 Redux/Schematics.pdf`의 Redux 회로도, 같은 디렉터리의 microcode CSV, `../manual.txt`, [SST39SF040 데이터시트](https://ww1.microchip.com/downloads/aemDocuments/documents/MPD/ProductDocuments/DataSheets/SST39SF010A-SST39SF020A-SST39SF040-Data-Sheet-DS20005022.pdf). 전체 진행 및 미완료 항목은 `../PROGRESS.md`에 기록한다.
