# minredux-gui

`minredux`의 흑백 Redux 에뮬레이터 코어를 그대로 사용하는 창 기반 프론트엔드다.
터미널 문자 인코딩 대신 400x240 VRAM 뷰포트를 직접 픽셀로 렌더링하고,
호스트 키를 MinOS가 기대하는 UART 바이트로 변환한다.

## 빌드와 실행

```sh
cd minredux/gui
cargo run --release
```

기본 ROM은 `minimal64/Revision 1.4 Redux/FLASH Images/`를 자동으로 찾는다.
Forth 커널을 부팅하려면 이미지 경로를 지정한다.

```sh
cargo run --release -- --rom-dir ../../minforth/build
```

창을 닫으면 종료한다. `F5`는 CPU를 리셋한다. 터미널 프론트엔드처럼
Ctrl-]를 누를 필요는 없다.

## 입력

- Enter는 LF `0x0a`, Backspace와 Delete는 `0x08`로 보낸다.
  MinOS `OS_ReadLine`이 기대하는 값이며, 터미널의 CR `0x0d`/DEL `0x7f`
  불일치를 피한다.
- Shift로 대문자와 기호를 입력하고, Caps Lock 상태는 창 안에서 토글한다.
- Ctrl+문자는 `0x01..0x1a` 제어 코드가 된다.
- 화살표·Home/End·기능 키는 MinOS 라인 편집기가 해석하지 않으므로 보내지 않는다.

## 옵션

```sh
# 2배 크기, 5배속
cargo run --release -- --scale 2 --speed 5

# 색상 지정 (RRGGBB)
cargo run --release -- --fg e0ffd0 --bg 101410

# 90프레임 뒤 종료하고 BMP 스크린샷 저장
cargo run --release -- --frames 90 --screenshot boot.bmp

# 창 없이 스크린샷과 텍스트 화면만 생성
cargo run --release -- --headless --frames 120 --screenshot boot.bmp --text
```

`--speed`는 60fps마다 실행할 CPU 클록을 배율로 정한다. 기본값 `1.0`은
프레임당 133,120클록, 즉 실제 8MHz Redux와 같은 속도다. `--headless`는
`--frames`가 필요하며 화면 갱신 없이 빠르게 실행된다.

`--uart-hex`로 부팅 후 입력을 미리 넣을 수 있다. 기본 `--uart-after 200000`
동안 기다리므로 MinOS 배너 이전 입력이 사라지지 않는다.

```sh
cargo run --release -- --headless --frames 400 --rom-dir ../../minforth/build \
  --uart-hex 6d696e666f7274680a3a20742030203130203020444f2049202b204c4f4f50202e203b0a740a \
  --text
```

## 구조

- `src/frame.rs`: VRAM `(96,12,400,240)` 크롭, 정수 배율 확대, 24-bit BMP 출력.
- `src/input.rs`: `minifb::Key` → MinOS UART 바이트 변환.
- `src/main.rs`: ROM 로드, 60fps 시뮬레이션, 창/헤드리스 실행, CLI.

코어 에뮬레이터는 수정하지 않는다. `minredux`는 계속 외부 crate 의존성이
없고, GUI 의존성(`minifb`)은 이 crate에만 들어간다.

## 검증

```sh
cd minredux/gui
cargo test
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

프레임 크롭·비트 순서·배율·BMP 인코딩·키 매핑을 단위 테스트한다.
실제 ROM 부팅 확인은 위 `--headless --screenshot` 예시로 수행한다.
