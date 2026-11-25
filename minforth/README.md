# Minforth 커널 노트

`forth/kernel.fs`는 프로젝트 전처리기를 쓰는 어셈블리이며, **호스트 Forth가 아니다**.
런타임 Forth 코드는 MinOS가 `minforth`를 실행한 뒤 커널에 입력한다.

## `ABORT"` (컴파일 전용)

```forth
: require-nonzero 0= ABORT" zero rejected" ;
0 require-nonzero
1 2 + .
```

이 예제는 `zero rejected`를 출력하고 인터프리터로 돌아간다. 다음 입력 줄은 `3`을 출력한다.
이 기능은 커널의 기존 비교·나눗셈 의미를 바꾸지 않는다.

런타임 스택 효과는 `( flag -- )`다.

- 0이면 flag만 소비하고 inline counted string을 건너뛴 뒤 현재 단어를 계속 실행한다. 스택의 다른 값은 그대로 남는다.
- 0이 아닌 16비트 값이면 메시지와 개행을 출력하고, 모든 호출자를 버린다.
  현재 입력 줄의 나머지를 폐기하고 REPL로 돌아간다.
- 데이터 SP와 하드웨어 리턴 SP는 `fe`가 되고, 루프 스택은 `2800`에서 빈 상태가 된다.
  루프 캐시, 컴파일러·제어 스택 깊이, 대기 중인 LEAVE 수를 초기화한다.
  이전 저장 공간을 0으로 채우지는 않지만 더 이상 접근할 수 없다.
- BASE, 완료된 사전 정의, 변수 내용은 유지된다.
- 다른 정의를 컴파일하는 도중에 immediate 단어가 abort하면, HERE와 LATEST가 그 colon 헤더 직전의 checkpoint로 롤백된다.
- 인터프리트 상태에서 직접 쓰거나 닫는 따옴표가 없으면 진단 메시지를 내고 같은 복구·롤백을 한다.
  일부만 만든 inline 코드는 남기지 않는다.

메시지는 **같은 입력 줄**의 닫는 따옴표까지 이어지는 원시 ASCII다.
구분용 공백 한 칸은 건너뛴다. 공백과 대소문자는 보존하고, 빈 문자열도 허용한다.
escape 문법이나 여러 줄 문자열 확장은 없다.
UART 입력 줄은 기존 편집기 한도(도우미 스크립트 기준 46열) 안에 둔다.
이것은 일반적인 CATCH/THROW 구현이 아니다. catch 가능한 예외 코드나 독립된 공개 ABORT 단어는 추가하지 않는다.

컴파일러 checkpoint는 RAM `26c0..26c3`(`forth/defs.inc`의 `nfDefHere`, `nfDefLatest`)을 예약한다.
커널 코드는 이 주소보다 앞에서 끝나야 한다.
컴파일된 `ABORT"`는 기존 `."`와 같은 `JPS wABORTQRT / 길이 바이트 / 메시지` 배치를 쓴다.
false 경로는 페이지 경계를 넘는 경우에도 호출자 리턴 주소를 바로잡는다.

## 컬러 + SN76489 확장 단어

CS-DRAFT-1 보드(`hardware/redux-color-sound/`, 에뮬레이터는 `minredux-cs/`)용 단어다.
레지스터는 `0xFEE0..0xFEEF`에 있다. `hardware/redux-color-sound/CIRCUIT.md`를 참고한다.

| 단어 | 스택 | 동작 |
| --- | --- | --- |
| `COLOR` | `( flag -- )` | 컬러 출력 켜기/끄기(제어 bit 0) |
| `AUDIO` | `( flag -- )` | line-out mute 해제/설정(bit 3). 먼저 `SILENCE`를 보낸다 |
| `ATTR!` | `( attr col row -- )` | 8x8 셀 하나의 색. col 0..49, row 0..29 |
| `ATTRFILL` | `( attr -- )` | 50x30 셀 전체의 색 |
| `SN!` | `( byte -- )` | SN76489 명령 바이트 하나를 그대로 전송 |
| `TONE` | `( period ch -- )` | 톤 채널 0..2, 10비트 주기, f = 3579545/(32*N) |
| `VOL` | `( atten ch -- )` | 채널 0..3(3 = 잡음), 0이 가장 크고 15는 끔 |
| `NOISE` | `( mode -- )` | 잡음 제어. bit 2는 white, bit 0..1은 속도 |
| `SILENCE` | `( -- )` | 네 채널 모두 감쇠 15 |

`attr`는 `background<<4 | foreground`이고, 각 니블은 `I:R:G:B`다.
`ATTR!`는 `0x440c + row*512 + col`(셀의 4번째 줄)에 쓴다.
보드의 CPU 쓰기 경로가 Attribute 행을 +4 adder 없이 A13..A9에서 바로 가져오기 때문이다.

```forth
HEX 1E ATTRFILL 4F 0 0 ATTR! DECIMAL 1 COLOR
SILENCE 254 0 TONE 0 0 VOL 1 AUDIO     \ about 440 Hz on channel 0
```

- flag는 셀 전체로 판정한다. 16비트 값이 0이 아니면 켠다.
- 제어 레지스터는 쓰기 전용이다. `zXCTL`(ZP `0x9e`)이 bit 0과 3을 shadow로 보관한다.
  부팅 시 RESET 상태와 맞추려고 0으로 지우며, 단어들은 하드웨어 값을 다시 읽지 않는다.
- bit 1(SN strobe)과 bit 2(Attribute plane)는 단어 안에서만 켜고 반환 전에 끈다.
  Attribute 모드는 MinOS 출력이 쓰는 `0x4000` 비트맵 mirror의 CPU 읽기를 막기 때문이다.
- `ATTR!`는 row ≥ 30 또는 col ≥ 50(하위 바이트 기준)을 무시한다. 그래서 어떤 쓰기도 비트맵 창을 벗어나 사전을 덮어쓰지 않는다.
  Attribute는 텍스트와 함께 스크롤되지 않는다. MinOS 스크롤은 비트맵 바이트만 옮긴다.
- SN 전송은 회로 문서의 순서를 따른다: READY 대기 → 데이터 유지 → CE/WE assert →
  **assert한 상태에서** READY high 대기 → 해제.
  READY 대기는 각각 256회 폴링 후 포기한다. 그래서 확장 회로가 없는 보드에서도 멈추지 않는다.
  그런 보드에서는 이 주소 창이 일반 RAM이라 쓰기는 무해하지만, 소리는 나지 않는다.
- 커널은 부팅 시 확장 회로를 건드리지 않는다. SN76489에는 리셋 입력이 없으므로 `1 AUDIO` 전에 `SILENCE`를 실행한다.
- 이 단어들은 primitive 테이블의 가장 오래된 쪽에 있다. 그래서 최신 정의부터 찾는 일반 `FIND` 검색이 이 단어들을 먼저 훑지 않는다.

커널과 release 실행 파일을 다시 빌드한 뒤 `minredux-cs/`에서 `python3 ext_regress.py -v`를 실행한다.
end-to-end 검사 7개는 다음을 확인한다: Attribute 셀과 범위 보호, 전체 채우기, 제어 shadow, SN 레지스터,
WAV에서 측정한 440Hz 톤, PPM 팔레트. 모든 경우에 SN 프로토콜 오류와 VREG 덮어쓰기가 0이어야 한다.

## 격리된 이미지 빌드와 테스트

저장소 루트에서 실행한다.

```sh
python3 minforth/tools/build.py minforth/forth/kernel.fs minforth 0x1000 --out minforth/build-p1
```

커널 빌더는 `minforth.bin`과 같은 전처리 소스·어셈블러 결과에서 `minforth.symbols.json`도 만든다.
함께 쓰는 제어 ROM은 **`minimal64/Revision 1.4 Redux/FLASH Images/`**에서 복사한다. 이 경로에 수정 ROM이 직접 설치되어 있다.
원본 ROM이나 별도 `roms/` 번들은 필요 없다. `python3 minredux/verify_rom.py`가 빌드 전에 수정본 hash와 CSV를 검사한다.
커널은 checkpoint RAM `26c0`보다 앞에서 끝나야 한다.

`minredux/`에서 필요하면 release 프론트엔드를 다시 빌드한 뒤 실행한다.

```sh
cargo build --release
python3 regress.py --rom-dir ../minforth/build-p1
python3 abort_regress.py --rom-dir ../minforth/build-p1 -v
```

ABORT 전용 검사 13개는 다음을 확인한다.

- 셀 전체 기준의 참 판정과 false일 때 계속 실행
- 입력 echo가 아니라 실제 메시지 출력
- 같은 줄의 나머지 폐기
- 중첩 호출자와 리턴·루프 스택
- DO/LEAVE patch를 포함한 미완성 정의 롤백
- BASE·사전·변수 보존, 반복 abort, 페이지 경계를 넘는 inline 문자열

P1 측정 하네스는 `../benchmark.md`를 참고한다.

## P2 컴파일러·스택 최적화

- 마지막으로 컴파일된 `JPS`는 그 뒤에 리터럴, 문자열, 분기, 다른 바이트가 없을 때만 `JPA`로 바꾼다.
  정의 끝으로 가는 forward 분기는 그 목적지에 `RTS`를 남긴다. `EXECUTE`, `>R`, `R>`, `R@`는 호출 프레임을 유지한다.
- `DROP`, `I`, `+`, `1+`, `C@`는 이름이 아니라 primitive **xt** 기준으로 inline한다.
  재정의와 인터프리트 실행은 여전히 일반 사전 검색을 쓴다.
  템플릿은 위치 독립적이어야 하고 리턴 프레임을 보면 안 된다.
  `@`/`!`는 절대 주소 INCW 분기를 포함하므로 이 방식으로 그대로 복사할 수 없다.
- 이항 산술·비교와 store는 이제 `zSP`를 직접 움직여 스택 셀을 소비한다. NP 설정·복사를 하지 않는다.
  split-byte 배치와 8비트 SP 동작은 바뀌지 않았다. overflow/underflow 검사를 추가한 것은 아니다.
- `zLastCall`(`9a..9b`), `zTailOK`(`9c`), `zEndTarget`(`9d`)은 컴파일러 전용 상태다.
  바이트를 내보내는 모든 함수는 뒤의 두 값을 무효화해야 한다. 현재는 정의에 들어가는 모든 바이트가 `nf_cbyte`를 거친다.

P2 완료 시점의 커널은 4,988바이트로 `237c`에서 끝났다.
컬러·음원 단어를 추가한 현재 커널은 5,401바이트로 `0x1000..0x2518`을 차지하며, 여전히 checkpoint RAM `26c0`보다 앞에서 끝난다.
inline은 실행 클록을 줄이는 대신 사전 크기와 컴파일 시간을 늘린다. 전후 측정값은 `../benchmark.md`에 있다.

현재 기본 이미지는 저장소 루트에서 `--out` 없이 다시 빌드한 뒤 `minredux/`에서 확인한다.

```sh
python3 regress.py
python3 abort_regress.py
python3 p2_regress.py
```

P2 검사는 생성된 명령, 유지된 분기·리턴 목적지, inline 바이트 동일성, RAM 결과(carry/borrow와 메모리 페이지 경계 포함)를 확인한다.
UART 입력 echo를 출력으로 인정하지 않는다. `../minforth/build`와 그에 맞는 심볼 파일을 사용한다.
