# Min vs Forth 벤치마크

## 목표와 범위

동일 Redux CPU·제어 ROM에서 Min 토큰 인터프리터와 16비트 Forth의 동일 알고리즘 실행 비용을 비교한다. 공식 CoreMark/Embench 점수가 아닌 프로젝트 전용 스위트다. 기존 `speed.fs`의 59.22배는 해당 작업의 기존 통합 측정값이며 전체 성능을 대표하지 않는다.

## P1 하네스 v2 (2026-10-30)

기존 7종의 알고리즘·입력·raw hook 측정은 유지하고 **정밀 준비 단계·컴파일/토큰화·메모리 관찰·전후 비교**를 추가했다. 아래 v1 표/진행 기록은 당시 결과를 보존한 것이다.

```sh
# 7종 + empty + 호출/스택/DO/파서 진단 4종, 반복 측정과 관찰자 무영향 검사
python3 benchmarks/run.py --stage 3 --diagnostics --repeat 2 --verify-profile

# 동일 제어 ROM의 기존 결과와 클록/크기/단계별 비용 비교
python3 benchmarks/run.py --baseline benchmarks/results/baseline-original-v1/results.json
python3 benchmarks/compare.py BASELINE/results.json CANDIDATE/results.json
```

### 정확한 경계와 계측 방식

`build.py`가 실제 전처리/어셈블 결과의 `minforth.symbols.json`을 저장한다. Min과 MinOS도 공식 소스에서 심볼을 추출하되, **모든 명시적으로 emit된 바이트가 배포 FLASH의 실행 파일과 일치해야만** 사용한다. Min의 626개 미출력 page-padding 바이트는 배포본 00 / flat helper ff로 달라서 비교에서 제외한다. 실행되는 배포 Min 프로그램은 교체하지 않는다. 검증한 심볼과 소스/실행 파일 hash는 결과에 저장한다.

PC뿐 아니라 `SC=0`, 하드웨어 SP와 실제 JPS 복귀 주소로 함수 진입/복귀를 대응시킨다. 함수 첫 주소로 되돌아가는 내부 루프를 새 호출로 세지 않는다. MinOS API trampoline만 추적하면 초기 prompt나 내부 호출을 놓치므로 **검증한 OS_Prompt/OS_ReadLine/OS_LoadFile 실제 주소**를 사용한다. CPU 명령이나 guest RAM은 수정하지 않는다.

`phases`는 다음 **상호 배타적** 클록 분류다. 합은 RESET부터 끝 hook까지 `end_cycle`과 정확히 같아야 하고, `execute`는 기존 `raw_cycles`와 정확히 같아야 한다.

| 필드 | 범위 |
| --- | --- |
| `boot` | RESET → 최초 OS_Prompt 명령 진입 (READY 출력 이전 경계) |
| `application_boot` | Forth wBoot → 최초 wRepl / Min 진입 → 최초 Block 중 다른 단계에 속하지 않는 초기화 |
| `input` | OS_ReadLine 진입 → 동일 호출의 복귀. 대기·echo 포함, 컴파일 시간에는 포함하지 않음 |
| `load` | OS_LoadFile 및 Min Loader. 중첩되더라도 한 클록은 한 번만 집계 |
| `tokenize` | Min Tokenizer 전체 / 컴파일 핸들러 밖의 Forth nf_next |
| `compile` | Forth nf_word의 컴파일 상태 토큰 및 `:`/VARIABLE/CONSTANT/IMMEDIATE 정의 처리. lookup·숫자 파싱·이름 파싱·코드 생성 포함, 줄 입력 대기는 제외 |
| `setup_execute` | 시작 hook 이전의 Forth 해석 실행 (예: 입력 배열 init 함수, 해석된 리터럴) |
| `dispatch` | 위 단계에 속하지 않는 준비/명령 dispatch. Min의 토큰화 후 top-level 초기화 실행도 여기에 포함 |
| `execute` | 시작 hook → 끝 hook. 프로토콜 overhead 포함 방식은 v1 그대로 |

따라서 Min은 `compile=0`이고 준비 코드 변환 비용은 `tokenize`로 보고한다. Forth 컴파일 앞의 외부 lexical 토큰화 비용은 별도 `tokenize`이며, 둘을 합치면 해당 source-processing 구간이다. 서로 다른 언어의 두 단계를 억지로 동일 컴파일러 작업으로 간주하지 않는다.

`components`/`calls`는 nf_parse·nf_find·nf_next·nf_cbyte 등의 **포괄적** 함수 비용/호출 수다. 부모와 자식 비용이 겹칠 수 있으므로 합산하지 않는다. 특히 `forth_parse`는 실제 숫자 변환 함수 내부만 측정하며 UART·lookup·기계어 emit 비용은 포함하지 않는다.

### 코드 크기와 메모리 high-water

- `runtime_code_bytes`: 실제 런타임 native binary 크기 (현재 Min 6,528 / Forth 4,743 bytes), 공통 MinOS는 제외.
- `dictionary_bytes`: 기존 HERE-8000. `compiled_dictionary_bytes`: 여기에 최초 wRepl의 boot dictionary를 뺀 **이번 소스의 헤더·변수·정의·init 함수·bench wrapper 증가량**. 단일 알고리즘 body 크기만 뜻하지 않는다.
- Min `source_bytes`/`token_bytes`: Loader/Tokenizer 복귀 시 실제 포인터로 얻은 resident span. NUL/종료 토큰 포함.
- Min call/variable dictionary 및 임시 데이터/식/지역변수 영역: **실제 RI write 주소**의 최대 span. 예: `temporary_data_written_span_bytes`는 3a00..3f7f 내 마지막 실제 쓰기까지의 범위다.
- Forth 데이터 스택 peak cells / 루프 프레임 peak bytes와 양쪽 hardware stack peak bytes도 관찰한다. 8비트 순환 스택의 무제한 깊이나 모든 overflow 부재를 증명하는 것은 아니다.
- 입력/출력 workspace의 written span은 gap을 포함할 수 있다. 서로 겹치는 live allocation의 합이나 전체 메모리 총량이 아니므로 항목을 무조건 더하지 않는다. 고정 예약량·native code·동적 관찰값을 구분한다.

### 진단 4종과 비교 정책

| 케이스 | 작업 | 주로 볼 지표 |
| --- | --- | --- |
| `micro-call` | 작은 inc1 함수 64회 | raw 클록·컴파일 크기, future tail-call 영향 |
| `micro-stack` | 64회 산술, Forth OVER/SWAP/DROP | 스택 조작을 포함한 해당 작업 비용; 순수 단일 단어 비용은 아님 |
| `micro-do` | 64회 짧은 3회 루프 진입 | DO 진입/중첩 루프 비용 |
| `micro-parse` | 4자리 상수 32개 포함 정의 | nf_parse 포괄 비용·횟수, 컴파일 비용·크기 |

진단 항목은 종합 언어 점수에 넣지 않는다. Min은 같은 계산 결과를 내지만 표현 방식이 달라 Forth 내부 단어별 비용과 직접 동등하지 않다. 파서 비용에도 wrapper의 숫자들이 포함되므로 숫자 개수/호출 수를 함께 본다.

비교 도구는 PASS한 결과끼리, 동일 제어 ROM hash·입력 모드·케이스 파라미터·독립 정답 hash에서만 비교한다. 반복 불일치/미검증 결과는 거부하고 source가 바뀌면 명시한다. raw 클록 변화율, dictionary/compiled bytes 변화, v2끼리는 단계별 비용 차이를 JSON과 표로 제공한다. v1에 없는 세부 항목을 추정해 채우지 않는다.

`--verify-profile`은 케이스마다 **관찰자 없이도 한 번 더 실행**하여 시작/종료/클록/스택 값과 전체 64KiB RAM이 일치하는지 검사한다. JSON의 `observer_verified`에 결과를 기록한다. 호스트 실제 경과 시간은 CPU 가상 클록과 혼동하지 않는다.

v2 원본 ROM의 측정 예 (숫자는 준비 구간/정의 규모에 대한 값이며 실행 클록 표와 별개):

| 작업 | Min 토큰화 클록 | Forth 컴파일 클록 | Forth 정의 증가 bytes | nf_parse 클록 / 호출 수 |
| --- | ---: | ---: | ---: | ---: |
| empty | 8,148 | 35,758 | 43 | 3,952 / 2 |
| Matrix | 259,942 | 595,755 | 736 | 21,897 / 24 |
| Mandelbrot | 364,371 | 880,026 | 1,000 | 24,254 / 25 |
| micro-call | 95,924 | 110,150 | 152 | 7,665 / 6 |
| micro-stack | 68,157 | 133,710 | 161 | 8,117 / 7 |
| micro-do | 94,598 | 119,231 | 194 | 8,569 / 8 |
| micro-parse | 243,998 | 639,556 | 601 | 57,420 / 36 |

현재 설정의 최초 OS_Prompt 경계는 양쪽 모두 **218,975클록**이다. Min 재귀 Fib(6)의 observed hardware stack peak는 **234 bytes**로 256바이트 하드웨어 스택의 제약도 실제 수치로 드러난다. 관찰된 span/peak를 전체 live memory 또는 더 깊은 재귀의 안전성으로 일반화하지 않는다.

## 단계별 진행

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 1 | 측정 실행기·독립 정답·Sieve/Bubble sort/Matrix multiply/재귀 Fibonacci | 완료 |
| 2 | CRC-16·바이트 문자열 검색 추가, 총 6종 | 완료 |
| 3 | 고정소수점 Mandelbrot 추가, 총 7종 | 완료 |

원본·수정 제어 ROM 각각에서 7종+empty, Min/Forth 각각 2회: 총 **64회**의 실행·정답·스택·반복 클록 검사 통과. 세 단계의 순서는 아래 진행 기록에 보존한다.

## 측정 원칙

- 원본 ROM과 커널/FLASH를 덮어쓰지 않고 격리된 이미지를 생성한다.
- 같은 제어 ROM을 양쪽에 적용하고 ROM·커널·소스 hash를 결과에 기록한다.
- 입력 초기화, 실행, 정답 검증을 구분한다. 실행 중에는 화면/UART 출력을 하지 않는다.
- 화면 문자열 polling 대신 매 CPU 클록의 명령 경계에서 공통 측정 hook 진입을 감지한다.
- hook 호출 및 언어 dispatch 비용을 포함하는 raw 구간을 보고하고 빈 작업의 같은 프로토콜 비용도 별도 보고한다. 이를 순수 산술 클록으로 부르지 않으며 자동 차감하지 않는다.
- 준비 구간에는 부팅·파일 로드·Forth UART 입력/컴파일 또는 Min 토큰화가 포함된다. 준비 시간은 언어간 순수 컴파일 성능 점수로 사용하지 않는다.
- 입력 크기·자료형·연산 순서를 고정하고 호스트의 독립 reference와 결과 전체를 비교한다.
- 언어별 메모리 표현 차이를 명시하고, 소스 bytes와 Forth HERE 증가량을 전체 메모리 사용량으로 혼동하지 않는다.
- 결과가 틀리거나 hook 누락·timeout·스택 불균형이면 실패한다. 원시 클록의 항목별 배율을 기본 보고하며, 종합 점수는 발표하지 않는다.

## 실행

워크스페이스 루트에서 실행한다. Python 3 표준 라이브러리, Rust/Cargo, 네이티브 `minforth/tools/asm`이 필요하다. 실행기는 release observer와 현재 소스의 커널을 자동 빌드하며 기존 `minforth/build/` 및 원본 ROM은 변경하지 않는다.

```sh
# 단계별 실행: 4종 → 6종 → 7종 (empty는 매번 추가)
python3 benchmarks/run.py --stage 1
python3 benchmarks/run.py --stage 2
python3 benchmarks/run.py --stage 3

# 특정 항목, 반복 횟수 및 전체 부팅 포함 클록 상한
python3 benchmarks/run.py --case matrix --case mandelbrot --repeat 3 --max-cycles 300000000

# 호스트 reference·소스 생성·오류 검출 검사
python3 -m unittest discover -s benchmarks -p 'test_*.py'
```

`--out DIR`로 **새 디렉터리**를 지정하거나 기본 `benchmarks/results/run-*`를 사용한다. 기존 디렉터리를 덮어쓰지 않는다. 각 실행 폴더에 양쪽 소스, UART 입력, 실제 ROM/FLASH, 반복별 64KiB RAM, `results.json`을 저장한다. 실패 시 JSON에 원인과 자식 프로세스 진단을 남기며 비정상 종료한다. host timeout은 guest 실행당 기본 180초(`--host-timeout`으로 조정), 가상 클록 상한은 기본 300,000,000이다. 관찰자는 host 실행 속도를 낮출 수 있으므로 바쁜 호스트에서 전체 스위트 검증은 충분한 시간을 허용한다. SIGTERM/KeyboardInterrupt도 실패로 기록하며, 강제 종료 등으로 `status=running`이 남은 결과는 완료로 취급하지 않고 비교에서도 거부한다.

### 결과 필드

- `start_cycle`: RESET부터 시작 hook까지. 부팅·로드·컴파일/토큰화·초기화를 포함하는 **준비 구간**이지 순수 컴파일 시간은 아니다.
- `raw_cycles`: `sc=0, BANK=ff`에서 `df00` 진입부터 `df10` 진입까지. 시작 hook의 RTS와 끝 hook에 도달하기 위한 언어별 호출 준비/dispatch를 포함한다. 끝 hook의 RTS는 제외한다.
- `source_bytes`/`source_sha256`, 실제 FLASH·제어 ROM·커널 소스/defs·observer 실행 파일·케이스 정의 hash를 보존한다.
- Forth `dictionary_bytes`: 이 케이스의 정의·변수·초기화 함수 및 부팅 사전을 포함한 `HERE-8000`. Min의 총 메모리와 직접 대응하는 수치는 아니다.
- 가상 클록 반복 일치를 검사한다. 호스트 wall-clock/MHz를 언어 성능으로 사용하지 않는다.

## v1 기준 결과 (2026-10-29)

원본 제어 ROM과 수정 제어 ROM의 결과가 아래와 **동일**하다. 각 행은 같은 입력의 raw 구간이며, 배율은 `Min/Forth`다. 첫 번째 empty 행은 측정 프로토콜 비용 확인용으로 실제 알고리즘 성능 점수에서 제외한다.

| 작업 | 고정 입력 | Min 클록 | Forth 클록 | 배율 |
| --- | --- | ---: | ---: | ---: |
| empty | 작업 없음 | 250 | 123 | 참고용 |
| Sieve | 소수 `<1024`, byte 배열 | 12,619,266 | 1,654,698 | 7.626× |
| Bubble sort | 32개, `(i*109+37)%251` | 6,330,757 | 951,076 | 6.656× |
| Matrix multiply | 4×4, 0..7 정수 | 955,799 | 398,408 | 2.399× |
| Recursive Fibonacci | n=6, naive recursion | 111,788 | 11,231 | 9.954× |
| CRC-16/MODBUS | 128 bytes, `(i*17+3)&255` | 8,229,138 | 988,412 | 8.326× |
| Byte search | 128 bytes, `ABABA`, 겹침 허용 | 2,668,976 | 521,353 | 5.119× |
| Mandelbrot | 16×12, scale=32, 최대 24회 | 61,623,162 | 29,001,744 | 2.125× |

전체 baseline 산출물: `benchmarks/results/baseline-original-v1/results.json`, `benchmarks/results/baseline-fixed-v1/results.json`. 작업별 최종 출력 배열/셀 전체를 host reference와 비교했다. Forth 데이터 SP, 양쪽 하드웨어 리턴 SP, Forth 루프 프레임 및 컴파일 상태도 검사했다. 결과 저장 경로는 `.gitignore` 대상이며 이 문서의 표는 기준 기록으로 남긴다.

## 알고리즘 규격과 해석 한계

- 입력 데이터 준비는 원칙적으로 시작 hook 앞에서 수행한다. Sieve의 플래그 배열 초기화, CRC 레지스터 초기화 및 각 알고리즘의 지역 카운터 설정은 해당 알고리즘 작업의 일부다. 초기화 비용을 일괄적으로 제외했다고 주장하지 않는다.
- Bubble sort는 고정된 비교 횟수의 인접 교환 방식이며 early-exit 최적화는 없다. Matrix는 같은 i/j/k 순서의 단순 곱셈이다. 행렬 중간값은 signed 16비트 범위를 넘지 않는다.
- Min은 `%`를 지원하지 않아 준비 코드에서 나눗셈/뺄셈으로 같은 입력을 만든다. `+=`도 런타임 피연산자에 쓰지 않는다. 양쪽의 표현식/변수 접근 차이는 각 언어 구현의 비용으로 남긴다.
- CRC 규격은 init=ffff, reflected polynomial=a001, xorout=0. Min logical shift와 Forth `2/ 32767 AND`의 결과를 동일하게 맞춘다.
- Search는 같은 순서로 모든 시작 위치를 검사하고, 첫 불일치에서 해당 위치 검사를 끝낸다. 동일한 byte 버퍼를 쓰며 문자열 라이브러리나 네이티브 검색 helper를 호출하지 않는다.
- Mandelbrot는 정수 좌표 `cx=-64+6*col`, `cy=-36+6*row`, `z0=0`. 매 반복 시작에 탈출 검사 후 `x'=(x*x-y*y)/32+cx`, `y'=2*x*y/32+cy`를 **이전 x/y**로 계산한다. 나눗셈은 0 방향 절삭이며 탈출하지 않으면 24를 기록한다. byte 단위 반복 횟수 192개를 비교한다.
- Mandelbrot는 양쪽 모두 고수준 16비트 곱셈만 사용한다. `abs(x)>64` 또는 `abs(y)>64`를 먼저 검사해 제곱 오버플로를 피한다. Forth의 현재 unsigned 비교/나눗셈 및 `0<`를 signed 연산으로 가정하지 않고, 부호 비트 마스크와 양수 나눗셈으로 부호를 명시 처리한다. 부동소수점/고정밀 Mandelbrot 성능은 아니다.
- 현재 v1은 작업별 하나의 크기/입력 분포다. 큰 배열, 정렬/역순/중복 입력, 깊은 재귀, 여러 Mandelbrot 영역은 후속 확장 대상이다. 7종 통과는 컴퓨터 전체 성능·전체 ISA 정확성·실기 타이밍의 증명이 아니다.
- v1 당시 미완료였던 정밀 단계 분리·메모리 high-water·자동 diff는 위 P1 v2에서 추가했다. v1의 기존 결과 파일 자체에는 그 필드가 없으므로 소급 측정값으로 해석하지 않는다.

## 진행 기록

- 2026-10-29: 3단계 구현 착수. 기존 하네스는 변경하지 않고 별도 도구를 추가한다.
- 1단계: `benchmarks/cases.py`, `benchmarks/run.py`, `minredux/examples/benchmark.rs` 추가. Sieve(상한 1024), Bubble(32개), Matrix(4×4), 재귀 Fib(6)와 empty protocol을 양쪽에서 독립 정답·반복 클록 일치로 확인.
- 선행 결함 수정: 기존 Forth `!`/`C!`/`+!`가 한 셀을 남기고 `*`가 피연산자를 남기는 문제, `/`/`MOD`의 stale `zNP` 의존을 수정. `minredux/regress.py`에 아래 셀을 보존하는 스택 회귀 6건 추가. 단순 출력 정답만으로는 이 결함을 발견하지 못했으므로 스택 균형 검사를 필수화.
- UART reflow에서 `VARIABLE`/`CONSTANT`/`:`와 다음 이름을 같은 줄에 묶음. 일반 문자열 지원 로더라고 주장하지 않음.
- 작업 공간은 VGA RAM을 피한 `d000..d1ff`(입력), `de00..df10`(hook 설치/진입), `e000..efff`(출력)로 분리. Forth 컴파일 중 화면 스크롤이 VGA RAM의 입력을 훼손하던 시제품 문제를 해결.
- 재귀 Fib(12)는 Min의 256바이트 하드웨어 스택 제약에서 실패하여 공통 지원 범위인 n=6으로 고정. 깊은 재귀 성능이나 재귀 안전성의 일반 증명을 주장하지 않음. 실패 실행도 각 run의 JSON과 RAM 진단으로 보존.
- 2단계 착수: CRC-16/MODBUS와 겹치는 패턴의 모든 출현을 세는 바이트 검색 추가.
- 2단계 완료: 원본 제어 ROM에서 기본 6종+empty를 각각 2회 실행하여 결과 전체·데이터/하드웨어 리턴 스택·루프 프레임·클록 재현성 확인. CRC는 `123456789 → 4b37` host 표준 벡터도 검사.
- 3단계 착수: scale=32 고정소수점 Mandelbrot, 16×12 픽셀·최대 24회·z0=0·탈출 조건 `x*x+y*y>4096`·signed division toward zero. 사전 좌표 범위 검사로 모든 곱셈 중간값을 signed 16비트에 유지하며 양쪽 모두 고수준 코드만 사용한다. Forth의 현재 `/`가 unsigned이므로 벤치마크 소스의 공통 정수 연산으로 부호를 처리한다.
- 3단계 완료: Mandelbrot 픽셀별 정답 및 2회 클록 일치 확인. 최종 원본/수정 ROM 각각에서 전체 7종+empty를 새 머신으로 2회씩 검증하여 총 64회 통과. host 검사 10건, Rust 전체 45건, Clippy·포맷 검사 통과.
- 커널 통합 검증: 격리 빌드의 원본·수정 제어 ROM에서 확장된 Forth 회귀 각각 **39/39** 통과. 현재 커널 산출물은 **4,472 bytes**. 기존 `minforth/build/` 및 기존 수정-ROM Forth 번들은 그대로이므로 새 회귀를 그 경로로 실행하려면 먼저 커널 재빌드/별도 번들 재생성이 필요하다.
