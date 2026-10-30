# min_forth

Minimal 64x4 (Revision 1.4 Redux) 홈 컴퓨터용 **16비트 Forth 커널**과, 그 하드웨어를 사이클 단위로 재현하는 **Rust 에뮬레이터** 저장소.

## 구성

| 경로 | 내용 |
| --- | --- |
| `minforth/forth/kernel.fs` | Forth 커널 본체. 호스트 Forth가 아니라 프로젝트 전처리기를 쓰는 어셈블리 소스 |
| `minforth/tools/` | C++ 어셈블러(`asm.cpp`), 이미지 빌더(`build.py`), 보조 스크립트 |
| `minforth/test/` | 커널 검증용 `.fs` 프로그램 |
| `roms/redux-1.4-isa-fixes-v1/` | ISA 결함 3건을 수정한 제어 ROM 번들. 에뮬레이터·벤치마크·커널 빌드의 기본 ROM |
| `minredux/` | 외부 crate 의존성 없는 Rust 에뮬레이터, ISA/화면 회귀 스크립트 |
| `benchmarks/` | Min 인터프리터와 Forth의 동일 알고리즘 실행 비용 비교 하네스 |
| `AGENTS.md` | 작업 공간 규칙과 커널 불변식 |
| `PROGRESS.md`, `benchmark.md` | 구현 이력, 벤치마크 방법과 결과 |

`minimal64/`(참조 ROM·MinOS·마이크로코드)와 `extended-min/`(별도 Min 인터프리터)은 각자의 저장소에서 관리되며 이 저장소에는 포함하지 않는다. `minimal64`의 원본 제어 ROM 이미지는 provenance/diff 용도로만 보존하고 명시 요청 없이 실행하지 않는다. 에뮬레이터를 실제로 돌리려면 해당 디렉터리가 로컬에 있어야 한다.

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

## 문서

- 커널 설계와 `ABORT"` 동작: [`minforth/README.md`](minforth/README.md)
- 에뮬레이터 사용법과 정확도 범위: [`minredux/README.md`](minredux/README.md)
- ISA 검증 내역: [`minredux/ISA_VALIDATION.md`](minredux/ISA_VALIDATION.md)
- 벤치마크 하네스: [`benchmark.md`](benchmark.md)
