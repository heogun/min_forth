# minredux-cs

Minimal 64x4 Revision 1.4 Redux의 **컬러 + SN76489 통합안(CS-DRAFT-1)**을 실행하는 Rust
디지털 에뮬레이터다. 기존 `minredux/`의 CPU·마이크로코드·FLASH·UART·PS/2·VGA 모델을
기반으로 하며, 흑백 기준 에뮬레이터인 `minredux/`는 그대로 보존한다. 외부 crate
의존성은 없고 Rust edition 2024 도구 체인이 필요하다.

새 하드웨어의 회로 근거와 알려진 한계는
[`../hardware/redux-color-sound/CIRCUIT.md`](../hardware/redux-color-sound/CIRCUIT.md),
[`../hardware/redux-color-sound/README.md`](../hardware/redux-color-sound/README.md)를
참고한다. **회로 초안은 배선·최악 조건 타이밍 검증과 실기 제작 검증이 끝나지 않았고,
이 에뮬레이터의 통과는 전기적 검증을 대체하지 않는다.**

## 빌드·검증

이 디렉터리에서 실행한다. Python 도우미는 release 실행 파일과 커널 이미지를 자동으로
다시 빌드하지 않는다.

```sh
cargo test --all-targets
cargo build --release
python3 regress.py
python3 abort_regress.py -v
```

`cargo test`는 CPU ISA·주변장치·확장 장치 검사이고, `regress.py`는
`../minforth/build`의 기존 Forth 커널 이미지를 쓰는 화면 출력 회귀다. 커널 재빌드는
저장소 루트에서 `python3 minforth/tools/build.py minforth/forth/kernel.fs minforth 0x1000`.
전체 ISA만 검사하려면 `cargo test tests::isa`. ROM hash/CSV 검증은
`python3 verify_rom.py`가 수행하며 수정 ROM은
`../minimal64/Revision 1.4 Redux/FLASH Images/`에 직접 설치된 이미지를 사용한다.

## 새로 모델링한 하드웨어

### 확장 I/O 창

`0xFEE0..0xFEEF`는 시스템 RAM 대신 확장 장치를 선택한다. 주소 bit 3은 디코드하지
않으므로 각 레지스터에 alias가 하나씩 더 있다.

| 주소 | 쓰기 | 읽기 |
| --- | --- | --- |
| `0xFEE0`, `0xFEE8` | SN76489 데이터 유지 래치 | `0xFF` |
| `0xFEE1`, `0xFEE9` | - | 상태 |
| `0xFEE2`, `0xFEEA` | 제어 레지스터 | `0xFF` |
| 나머지 | 무시, RAM 선택 안 함 | `0xFF` |

제어 레지스터는 하위 4비트만 유지한다.

| bit | 의미 |
| --- | --- |
| 0 | 컬러 출력 활성 |
| 1 | SN76489 쓰기 assert (`/CE`·`/WE` low) |
| 2 | Attribute 쓰기 모드 |
| 3 | 오디오 mute 해제 |

상태 바이트는 bit 0 SN READY, bit 1 Attribute 모드, bit 2 컬러, bit 3 오디오이며 상위
니블은 0이다. CPU RESET은 제어 레지스터만 지운다. SN76489에는 시스템 reset 핀이
없으므로 PSG 내부 상태는 유지된다.

SN 데이터는 제어 bit 1을 assert한 뒤 deassert하는 상승 에지에서 래치된다. READY는
strobe가 assert된 동안과 쓰기 후 32 입력 클록 동안 low다.

### Attribute SRAM과 컬러 팔레트

- 2KB Attribute SRAM을 별도로 모델링한다. 한 바이트는
  `background[7:4] | foreground[3:0]`이고 각 니블은 `I:R:G:B`다.
- 주소는 세로 위상 +4를 반영한 `((y + 4) & 255) >> 3` 행과 `x >> 3` 열이다.
  ViewPort 글자 `(column, row)`는 `(row + 2) * 64 + column + 12`에 대응한다.
- 채널 값은 `(2 * C + I) / 3` 스케일의 3단계(0, 1/3, 2/3, 1)다.
- Attribute 모드에서는 CPU의 `0x4000..0x7FFF` RAM 창이 inhibit된다. 쓰기는 기존
  VREG를 통해 캡처되며, 캡처 시점의 목적 plane(비트맵/Attribute)을 함께 저장한다.
  나중에 제어 bit 2를 바꿔도 이미 캡처한 쓰기의 목적지는 바뀌지 않는다.
- 표시 영역은 `12 <= column < 62`, `12 <= row < 252`다. 바깥은 검정으로 blanking한다.
- 컬러가 꺼져 있으면 Attribute를 무시하고 흑백 bypass로 출력한다.

### SN76489

- 입력 클록 3.579545MHz, 내부 16분주. 톤 주기는 `clock / (32 * N)`.
- 3개 톤 채널과 잡음 채널, 4개 2dB/step 감쇠기를 모델링한다. 네 채널 합이
  클리핑되지 않도록 채널당 최대 출력은 1/4 범위다.
- 원 SN76489 계열의 15비트 LFSR, tap `0x01`/`0x02`, `0x4000` feedback mask를 쓴다.
- 호스트 CPU와 다른 발진기이므로 fractional accumulator로 CPU 클록마다 전진시킨다.
  입력 에지는 CPU 클록 경계에 양자화되므로 평균 주파수는 정확하지만 sub-CPU-clock
  위상은 재현하지 않는다.
- 오디오 캡처는 제어 bit 3이 켜진 동안의 PSG 레벨만 기록한다. WAV는 mono 16-bit PCM,
  기본 48kHz이며 `rate * cycles / 8_000_000` 비율로 정확히 리샘플링한다.

## 실행

```sh
# 수정 제어 ROM + 변경 없는 MinOS
./target/release/minredux-cs run --cycles 400000 --no-output --text --stats

# Forth 이미지로 대화형 실행; Ctrl-] 로 종료
./target/release/minredux-cs term --rom-dir ../minforth/build --realtime

# 컬러 프레임과 SN 오디오를 파일로 저장
./target/release/minredux-cs run --rom-dir ../minforth/build --cycles 600000 \
  --ppm frame.ppm --wav audio.wav --audio-rate 48000 --ansi --stats
```

`--rom-dir`의 기본값은 `../minimal64/Revision 1.4 Redux/FLASH Images`다. 나머지
`run`/`bench`/`term` 옵션(`--uart-*`, `--input-mode`, `--ps2-*`, `--ascii`, `--text`,
`--trace`, `--dump*`, `--realtime` 등)은 `minredux/`와 같다.

추가 옵션:

| 옵션 | 내용 |
| --- | --- |
| `--ansi` | 50x30 텍스트 화면을 Attribute 전경/배경 24-bit ANSI 색으로 출력 |
| `--ppm FILE` | 표시 영역 400x240을 binary PPM(`P6`)으로 저장 |
| `--wav FILE` | SN76489 출력을 mono 16-bit WAV로 저장 |
| `--audio-rate N` | WAV 샘플레이트(기본 48000, 0 불가) |

`--stats`에는 `video_frames`, `vreg_overwrites`, `flash_busy_cycles`와 함께
`audio_samples`가 표시된다. `--ansi`는 터미널 ANSI 색 지원이 필요하고, `--text`는
기존과 같이 색 없이 디코드된 화면만 출력한다.

## 정확도 범위

- CPU·FLASH·UART·PS/2·VGA는 `minredux/`의 디지털 모델과 검증 범위를 그대로 따른다.
  `minredux/ISA_VALIDATION.md`의 ISA 한계와 수정 ROM 예외도 동일하게 적용된다.
- 컬러 경로는 **디지털 논리와 이상적인 3단계 DAC 값**을 모델링한다. 저항 공차,
  75Ω 부하, AC244 전파 지연, setup/hold, 최악 조건 타이밍은 재현하지 않는다.
- VREG는 여전히 한 항목짜리 pending write다. Attribute 쓰기도 같은 제한을 받으므로
  소프트웨어는 쓰기 간격과 덮어쓰기 가능성을 고려해야 한다.
- PSG는 데이터시트와 MAME 참조 동작을 따른 디지털 모델이다. READY 32클록은 설계
  참고값이며 실측 최대 지연을 보증하지 않는다. 아날로그 mixing, 앰프, 필터,
  발진기 오차, 전원 투입 과도 상태는 모델링하지 않는다.
- WAV 리샘플링은 구간 평균 방식이며 anti-alias 필터가 아니다.
- PPM은 VRAM과 Attribute SRAM의 최종 상태를 직접 읽어 만든 프레임이다. CRT의 실제
  blanking·타이밍 파형을 캡처한 것이 아니다.
- Attribute SRAM과 PSG의 전원 투입 값은 재현성을 위해 0/기본 상태로 시작한다.
  실기 부품의 미정 초기값을 재현하지 않는다.

## 파일 구성

| 경로 | 내용 |
| --- | --- |
| `src/lib.rs` | CPU/메모리/주변장치 `Machine`, I/O 분배, 텍스트·ANSI 출력 |
| `src/video.rs` | VGA, Attribute SRAM, plane-aware VREG, 팔레트, `frame_rgb` |
| `src/extension.rs` | `0xFEE0..0xFEEF` 디코드, 제어/상태, SN strobe |
| `src/psg.rs` | SN76489 톤·잡음·볼륨·READY 모델 |
| `src/audio.rs` | CPU 클록 오디오 캡처, 리샘플링, WAV |
| `src/isa_tests/` | 상속한 전체 ISA 검증 행렬 |
| `regress.py`, `runline.py`, `runfs.py` | Forth 커널 회귀·단일 입력·파일 실행 도우미 |
