# min_forth

Minimal 64x4 (Revision 1.4 Redux) 홈 컴퓨터용 **16비트 Forth 커널**과, 그 하드웨어를 사이클 단위로 재현하는 **Rust 에뮬레이터** 저장소.

## 구성

| 경로 | 내용 |
| --- | --- |
| `minforth/forth/kernel.fs` | Forth 커널 본체. 호스트 Forth가 아니라 프로젝트 전처리기를 쓰는 어셈블리 소스 |
| `minforth/tools/` | C++ 어셈블러(`asm.cpp`), 이미지 빌더(`build.py`), 보조 스크립트 |
| `minforth/test/` | 커널 검증용 `.fs` 프로그램 |
| `minimal64/Revision 1.4 Redux/FLASH Images/` | ISA 결함 3건을 수정한 ROM이 기존 위치에 직접 설치됨. 실행·빌드·검증의 단일 기준 |
| `minredux/` | 외부 crate 의존성 없는 흑백 기준 Rust 에뮬레이터, ISA/화면 회귀 스크립트 |
| `minredux/gui/` | `minredux` 코어를 사용해 400x240 VRAM을 직접 렌더링하는 창 기반 흑백 프론트엔드 |
| `minredux-cs/` | 컬러 + SN76489 통합안(CS-DRAFT-1)용 Rust 에뮬레이터. `minredux/`를 기반으로 확장 |
| `benchmarks/` | Min 인터프리터와 Forth의 동일 알고리즘 실행 비용 비교 하네스 |
| `AGENTS.md` | 작업 공간 규칙과 커널 불변식 |
| `PROGRESS.md`, `benchmark.md` | 구현 이력, 벤치마크 방법과 결과 |

`minimal64/`(수정 ROM·MinOS·마이크로코드)와 `extended-min/`(별도 Min 인터프리터)은 각자의 저장소에서 관리되며 이 저장소에는 포함하지 않는다. 삭제된 원본 ROM이나 별도 `roms/` 번들은 필요 없다. 위 기본 경로에 수정 이미지와 일치하는 CSV가 있어야 하며 `python3 minredux/verify_rom.py`로 검증한다.

## 빌드

```sh
# 네이티브 어셈블러 (최초 1회, 또는 asm.cpp 수정 후)
clang++ -O2 -std=c++11 minforth/tools/asm.cpp -o minforth/tools/asm

# Forth 커널 이미지: minforth/build/flash.bin 생성
python3 minforth/tools/build.py minforth/forth/kernel.fs minforth 0x1000
```

`build.py`는 `forth/defs.inc`를 앞에 붙이고 매크로/인클루드를 전개한 뒤, 목적지 인자와 일치하는 `#org`를 요구하고 결과를 MinOS 플래시 파일 시스템에 삽입한다. 참조 ROM을 건드리지 않으려면 `--out DIR`을 쓴다.

## 실행과 검증

```sh
cd minredux
cargo build --release

python3 regress.py                      # 커널 end-to-end 회귀
python3 runline.py ': t 0 10 0 DO I + LOOP . ;' 't'
./target/release/minredux term --rom-dir ../minforth/build   # Ctrl-] 로 종료
```

Python 도우미는 실행 파일과 ROM을 자동으로 다시 빌드하지 않으므로, 어셈블리나 Rust 소스를 고친 뒤에는 위 빌드 단계를 먼저 실행한다.

터미널 대신 실제 400x240 화면을 창에서 보려면 `minredux/gui`를 실행한다.
Enter를 LF `0x0a`, Backspace를 `0x08`로 보내므로 터미널의 CR/DEL 불일치가 없다.

```sh
cd minredux/gui
cargo run --release
cargo run --release -- --rom-dir ../../minforth/build   # Forth 커널
```

컬러·SN76489 통합안은 `cd minredux-cs`에서 같은 방식으로 빌드·회귀하며, 추가로
`--ansi`, `--ppm`, `--wav` 출력을 지원한다. 자세한 내용은
[`minredux-cs/README.md`](minredux-cs/README.md)를 참고한다.

## 문서

- 실물 제작 부품 구매 목록과 주의사항: [`docs/HARDWARE_SHOPPING.md`](docs/HARDWARE_SHOPPING.md)
- 커널 설계와 `ABORT"` 동작: [`minforth/README.md`](minforth/README.md)
- 흑백 기준 에뮬레이터 사용법과 정확도 범위: [`minredux/README.md`](minredux/README.md)
- 흑백 GUI 프론트엔드: [`minredux/gui/README.md`](minredux/gui/README.md)
- 컬러·SN76489 에뮬레이터와 한계: [`minredux-cs/README.md`](minredux-cs/README.md)
- ISA 검증 내역: [`minredux/ISA_VALIDATION.md`](minredux/ISA_VALIDATION.md)
- 벤치마크 하네스: [`benchmark.md`](benchmark.md)
- Cycle-exact 제안과 타당성 검토: [`CYCLE_EXACT_ROADMAP.md`](CYCLE_EXACT_ROADMAP.md), [`CYCLE_EXACT_REVIEW.md`](CYCLE_EXACT_REVIEW.md) (구현 승인/실기 검증 완료를 뜻하지 않음)
