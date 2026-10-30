# Redux ISA 검증

## 실행

`minredux/`에서 실행:

```sh
# ISA 검사 전체
cargo test tests::isa

# opcode별 검사 횟수 및 명령 의미 불일치 보고서
MINREDUX_ISA_REPORT=1 cargo test all_public_opcodes -- --nocapture

# 기존 즉시 산술 전수 검사도 포함한 전체 회귀
cargo test
```

## 검사 범위와 독립성

- 공개 opcode **0x00..0xfe, 255개** 모두에 명령 수준 기대값 검사가 있다. `0xff`는 assembler에서 `???`인 내부 OUT 대기 상태이며 별도 상태 전이 검사로 다룬다. 누락 opcode가 생기면 전체 coverage 검사가 실패한다.
- `src/isa_tests/`의 기대값은 제어 ROM을 다시 실행하는 방식이 아니다. 산술식, little-endian 메모리 연산, 주소지정 규칙 및 검토한 명령별 클록 표로 계산한다. 공개 opcode 이름과 operand 길이는 공식 `Support/Assembler/asm.cpp`와 교차 검사한다. 기존 524,288개 CSV/ROM 대조는 이 검사와 별개다.
- 전체 명령 행렬 **21,446개**에서 PC/MAR/BANK/IR, 정의된 A 결과, FR 전체, RAM 64KB 전체, FLASH 유지, UART/PS2 latch 및 UART 출력·완료 상태와 클록 수를 검사한다. long 연산의 조기 종료처럼 A가 명령 계약상 결과값으로 쓰이지 않는 경우 A 비교는 제외하고 메모리·플래그·제어 상태를 검사한다.
- 별도 전수 검사: 즉시 산술 ADI/SUI/CPI/ACI/SCI 입력·carry 조합 **458,752개**, 즉시 AND/OR/XOR **196,608개**, INV/DEV/NEV/LLV/RLV의 16비트 값·carry **655,360개**, CIV의 모든 16비트 목적지와 6개 임계값 **393,216개**. 전체 명령 행렬에는 모든 8비트 shift/rotate 입력·carry도 포함된다.
- 경계: opcode의 xxFF 위치, `ffff -> 0000` operand fetch 및 간접 pointer fetch, ZP `ff -> 0100`, 데이터 page/16비트 wrap, word/long carry·borrow·early exit, 조건 분기의 partial nibble-zero 상태, 스택의 SP=00/ff alias, JPS/JAS/RTS, WIN 입력 도착, OUT 및 내부 ff 대기 상태를 검사한다. WDB/WDR은 실제 unlock/program 명령열과 RDB 읽기를 함께 검사한다.
- A 결과·FI·RAM write·instruction-step 종료 신호를 각각 고장 낸 테스트 전용 ROM에 대해 oracle이 실패하는 mutation 검사 4개도 있다. 변경된 ROM을 그대로 정답으로 재해석하는 순환 검증이 아님을 확인한다.

**전체 opcode coverage는 전체 상태 공간의 전수 증명이 아니다.** 32비트 피연산자 전체 조합, 임의의 self-modifying code·operand alias 조합 및 모든 비동기 입력 도착 시각은 전수 검사하지 않는다. 이 검증은 소프트웨어 명령 수준이며 실기 타이밍 대조와 확장 포트는 사용자 결정으로 범위에서 제외한다.

## 배포 ROM에서 확인한 명령 의미 불일치

테스트 통과는 아래 결함이 사라졌다는 뜻이 아니다. 독립 기대값과의 차이를 명시적으로 검출한 뒤 **원본 ROM의 정확한 관찰 결과**를 검사한다. opcode별 Rust 보정이나 원본 ROM 변경은 하지 않는다.

세 결함의 수정본은 원본과 별개인 [`../roms/redux-1.4-isa-fixes-v1/`](../roms/redux-1.4-isa-fixes-v1/)에 저장했다. `cargo test fixed_rom`은 그 실제 이미지로 예외 없는 255-opcode 행렬 21,446건, XOR 전수 131,072건 및 WIN 도착 시점 4,608건 등을 검사한다. 원본의 아래 결함 회귀와 hash는 그대로 유지한다. 수정본의 생성법·clock/scratch 차이·전체 변경 manifest는 해당 디렉터리의 README를 참고한다.

### 0x52 BXR (`XR.B`): 목적지 writeback 누락

- 초기 A=1, RAM[1200]=0에서 `XR.B 0x1200`의 의도된 결과는 A=1, RAM[1200]=1이다.
- 원본은 A=1을 계산하지만 RAM[1200]은 0에 머무르고, scratch RAM[00ff]에 AND 중간값 0을 남긴다.
- 근거: `microcode_def.csv`의 `XR_B`는 scratch로 MAR을 바꾼 뒤 목적지 복원·최종 `RI`가 없다.

### 0x54 RXR (`XR.R`): scratch 주소로 writeback

- RAM[4500..4501]=0x1200, A=1, RAM[1200]=0에서 `XR.R 0x4500`의 의도된 결과는 RAM[1200]=1이다.
- 원본은 RAM[1200]을 변경하지 않고 최종 XOR 값 1을 RAM[00ff]에 쓴다. BXR과 달리 scratch에 AND가 아닌 XOR 값이 남는다.
- 근거: `XR_R`은 최종 `RI`가 있지만 MAR은 여전히 scratch 00ff를 가리킨다.
- 전체 행렬에서 두 opcode 각각 **7개**의 실제 의미 불일치를 검사한다. 허용 예외는 이 두 opcode의 목적지 유지뿐이며, A·플래그·클록·다른 RAM 위치는 일반 검사와 똑같이 비교한다.

### 0x04 WIN: ffff 대기 중 입력 도착 시 잘못된 주소로 wakeup

- ffff의 WIN에서 입력 없이 세 번 대기한 뒤 UART 또는 PS/2 바이트를 넣는다.
- 의도된 다음 PC는 0000이지만 원본 ROM에서는 **ff00**이 된다. 입력 latch는 소비되지 않는다.
- 원인: 실행 중 FI가 ready-input 제어 행으로 전환하면 low-byte 감소 단계는 건너뛰지만 carry=0인 high-byte 감소 단계는 실행된다.
- `win_waits_then_wakes_and_exposes_ffff_wakeup_rom_erratum`은 이 차이를 명시적으로 검사한다. 같은 검사에서 일반 주소 8000 및 page 끝 80ff의 정상 wakeup도 확인한다.

## 기타 ISA 주의점

- word/long 결과의 FR은 마지막으로 FI가 실행된 **바이트**의 플래그이지 전체 폭의 aggregate Z/N이 아니다. long add/sub의 네 번째 바이트 쓰기에는 FI가 없고, LR6/LR7도 최종 A와 다른 중간 연산의 플래그를 남긴다.
- ZP word의 두 번째 바이트는 0100으로 넘어갈 수 있다. 반면 일부 stack slot 주소는 low byte만 조합하고, RTS는 MAR 전체 증가를 사용하므로 오버플로한 프레임에서 0000/0001·00ff에 접근할 수 있다. 이상적인 추상 원형 스택으로 바꾸지 않는다.
- 명령 구현의 scratch RAM 00ff 변경도 observable한 부수효과로 검사한다. 특히 XOR·일부 logical right shift·JAS·WDB/WDR의 scratch 사용을 보존한다.

## 검증한 제어 ROM 식별

경로: `../minimal64/Revision 1.4 Redux/FLASH Images/`. 각 파일은 524,288 bytes이다. SHA-256:

```text
ctrl_lsb.bin d056f45db6da4c67d5b843cd49ec19879ac286204d036e34dd4ac68e6928ec34
ctrl_msb.bin 3b04671b89b859f84e9043e0fd6e5af015102241bad7318119154030e8db0f40
ctrl_hsb.bin d10100d6d9c7bb87c599fce032d4d39f7f75e5d4a4adefdc425b978c33864ad1
```

ROM를 갱신하면 위 알려진 결함 검사가 실패할 수 있다. 새 ROM의 수정 내용을 검토한 후 해당 예외와 문서를 함께 갱신한다. 검사를 통과시키기 위해 새 관찰값을 자동으로 기대값에 복사하지 않는다.
