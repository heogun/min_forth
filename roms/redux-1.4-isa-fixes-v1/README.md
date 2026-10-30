# Redux 1.4 ISA fixes v1

Carsten Herting(slu4)의 Minimal 64x4 Revision 1.4 Redux 마이크로코드에 확인된 결함 3건만 수정한 **별도 파생 이미지**다. 공식 upstream release가 아니다. 2026-10-30부터 에뮬레이터·벤치마크·커널 빌드의 기본 ROM이며, 원본 `minimal64/Revision 1.4 Redux/` 이미지와 `minforth/build/`는 provenance/diff 용도로만 보존한다. 원본 자료의 저작권·라이선스 조건은 그대로 적용된다.

## 저장된 파일

- `ctrl_lsb.bin`, `ctrl_msb.bin`, `ctrl_hsb.bin`: 각 512KiB의 수정 제어 ROM. MSB는 원본과 바이트 단위로 동일하다.
- `flash.bin`: 원본과 동일한 512KiB MinOS 2 프로그램 FLASH. Forth 커널 이미지는 아니다.
- `microcode_def.csv`: 수정 마이크로코드 정의.
- `microcode_rom.csv`: 원본과 동일한 flag/opcode 매핑.
- `manifest.json`: 버전, 원본/출력 SHA-256, 변경된 208개 제어 워드의 주소·수정 전후 논리값. 수정 바이트는 LSB 16개, MSB 0개, HSB 192개뿐이다.

## 변경 내용

| opcode | 수정 | 클록/호환성 |
| --- | --- | --- |
| 52 `XR.B` | MAR을 목적지에 유지하고 AND 중간값을 목적지에 임시 보관한 뒤 XOR 최종값을 writeback | 10클록 유지, FR 유지 |
| 54 `XR.R` | scratch로 향하던 MAR 변경을 제거하여 목적지로 최종 writeback | 13클록 유지, FR 유지 |
| 04 `WIN` | waiting-row step 1의 FI를 제거하고 기존 low-byte 감소 step 3에서 I/O와 carry를 함께 샘플링 | 입력이 이미 있으면 2클록, 무입력 대기 반복은 5/6클록 유지 |

수정한 XOR 두 명령은 이제 00ff scratch를 변경하지 않는다(00ff 자체가 목적지인 경우는 제외). WIN 실행 중 입력이 도착하면 현재 PC 되감기를 끝내고 다음 WIN poll에서 빠져나오므로 원본과 wakeup latency·중간 플래그는 달라질 수 있다. ffff 경계에서 ff00으로 잘못 깨어나는 문제를 해결한다.

배포 ROM의 reset 행(R=0) 및 다른 모든 opcode·제어 슬롯은 원본과 동일하다. Rust의 opcode별 우회 처리는 사용하지 않으며 이 파일들을 실제로 로드하여 실행한다. 실기 타이밍 대조 및 확장 포트는 프로젝트 범위에서 제외되어 있고, 이 이미지의 실기 사용 안전성까지 인증한 것은 아니다.

## 사용

워크스페이스 루트에서:

```sh
./minredux/target/release/minredux run \
  --rom-dir roms/redux-1.4-isa-fixes-v1 --cycles 400000 --no-output --text

./minredux/target/release/minredux term \
  --rom-dir roms/redux-1.4-isa-fixes-v1 --realtime
```

원본 이미지는 provenance/diff 용도로만 두며 명시 요청 없이 실행하지 않는다. 파일 교체는 필요 없다. `minredux/`에서 상대 경로를 쓰려면 `./target/release/minredux run ...`으로 실행한다.

## 재생성·검증

Python 3 표준 라이브러리만 사용한다. 루트에서:

```sh
python3 roms/build_redux_isa_fixes.py --check
python3 roms/build_redux_isa_fixes.py
cargo test --manifest-path minredux/Cargo.toml fixed_rom
```

생성기는 원본 제어 ROM hash 및 원본 CSV의 전체 재조립 결과를 확인한 다음 수정한다. 원본 디렉터리 내부 출력, 출력 파일 symlink 및 기존의 다른 내용 덮어쓰기를 거부한다. 같은 내용으로 재실행하는 것은 허용한다. `--check`는 파일을 쓰지 않고 재현성을 확인한다.

Forth와 함께 사용하려면 프로그램 FLASH만 Forth 이미지로 지정하여 **또 다른 출력 경로**를 만든다. 이 MinOS 번들을 덮어쓰지 않는다:

```sh
python3 roms/build_redux_isa_fixes.py \
  --out minforth/build-isa-fixes-v1 --flash minforth/build/flash.bin
```

그 다음 `minredux/`에서:

```sh
python3 regress.py --rom-dir ../minforth/build-isa-fixes-v1
./target/release/minredux term --rom-dir ../minforth/build-isa-fixes-v1 --realtime
```

이 번들은 기본 ROM으로서 예외 없는 255-opcode 행렬, XOR 두 명령의 모든 A/메모리 바이트 조합, WIN의 4,608개 주소·A/B·입력 경로·도착 시각 조합, 부팅 및 변경 범위/재현성 검사를 통과한다. 원본 이미지는 diff/provenance fixture로만 사용한다. 상세한 ISA 한계와 수정 전 결함 기록은 `../../minredux/ISA_VALIDATION.md`를 참고한다.

2026-10-29 검증 결과: Rust debug/release 각각 **45/45**, 포맷·Clippy 검사 및 번들 `--check` 통과. 별도로 생성한 `minforth/build-isa-fixes-v1/`와 기존 원본 제어 ROM 기반 Forth 이미지에서 회귀 각각 **33/33** 통과.
