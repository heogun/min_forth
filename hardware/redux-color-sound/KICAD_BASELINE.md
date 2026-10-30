# KiCad 원본 기준 검사

검사일: 2026-10-30. KiCad **10.0.7**.

**컬러·SN76489 통합 보드가 아니라 수정하지 않은 Redux 원본 CAD의 기준 검사다.**
새 회로를 붙이기 전부터 존재하는 진단을 구별하기 위한 결과이며 제조 승인이 아니다.

## 재현

저장소 루트에서:

```sh
python3 hardware/redux-color-sound/check_kicad.py
python3 -m unittest discover -s hardware/redux-color-sound -p 'test_*.py' -v
```

스크립트는 PATH 또는 macOS 기본 설치 위치에서 CLI를 찾는다.
현재 설치 경로는 `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`다.
별도 설치는 `--cli`, 표준 footprint 라이브러리는 `--footprints`로 지정한다.
KiCad 10 라이브러리 환경변수 `KICAD10_FOOTPRINT_DIR`도 사용할 수 있다.

- 원본은 `minimal64/Revision 1.4 Redux/KiCAD9/`이며 `--source`로 변경 가능하다.
- 전체 CAD 디렉터리를 임시 복사하고 복사본에만 표준 footprint 라이브러리를 연결한다.
- 기존 프로젝트의 custom library 경로는 보존하며 사용자 전역 설정을 변경하지 않는다.
- 원본 전체 파일의 SHA-256을 검사 전후 비교한다.
- `build/kicad-baseline/`에 ERC/DRC JSON, 명령 로그, `summary.json`을 생성한다.
- DRC에는 `--schematic-parity`를 지정한다. 오류·경고·제외 항목을 모두 보고하되
  요약에서는 제외 항목을 따로 세며, 제외를 통과로 오인하지 않는다.
- 이번 기준 검사는 저장된 zone 상태를 사용한다. `--refill-zones`나 `--save-board`는
  사용하지 않는다. 신규 PCB 제조 검사에서는 zone 재채움 후 별도로 검사해야 한다.
- 진단이 남으면 스크립트는 **종료 코드 1**, 실행 실패는 **2**다.
  이 기준 검사 결과는 의도적으로 0이 아니다. 경고를 없앤 것처럼 보고하지 않는다.
- 원본 프로젝트에서 비활성화한 검사 항목도 KiCad JSON의 `ignored_checks`에 남는다.
  `--severity-all`은 비활성화한 모든 검사 규칙까지 활성화한다는 뜻이 아니다.

## 결과

| 검사 | 분류 | 건수 |
| --- | --- | ---: |
| ERC | 활성 오류 | 0 |
| ERC | library symbol mismatch 경고 | 59 |
| DRC | 활성 오류 | 0 |
| DRC | library footprint mismatch 경고 | 4 |
| DRC | 미연결 항목 | 0 |
| PCB–회로도 parity | Description 등 symbol field mismatch 경고 | 90 |
| PCB–회로도 parity | 추가 footprint 경고 | 1 |
| PCB–회로도 parity | net conflict 경고 | 2 |
| DRC | 기존에 제외된 실크 텍스트 크기/두께 경고 | 3 |

실행 요약의 DRC 활성 진단 **97건 = DRC 4건 + parity 93건**이다.
검사 스크립트 단위 테스트 **6개 통과**, 원본 파일 hash 변경 없음.
KiCad 버전, 설치 라이브러리, 글꼴에 따라 숫자가 달라질 수 있다.

### 설치 직후의 라이브러리 경고와 구별

초기 실행에서는 표준 footprint 라이브러리가 전역 설정에 없어서 ERC 182건,
DRC 120건의 추가 library-link 경고가 발생했다. 복사본의 `fp-lib-table`에 설치된
표준 라이브러리를 연결하자 이 항목들은 사라졌다. PCB 배선을 고쳐 해결한 것이 아니다.

남은 symbol/footprint mismatch는 기존 내장 정의와 현재 참조 라이브러리 사이의
차이로 보고되었다. 일괄 갱신하면 핀 정의·풋프린트 형상·실크 등을 변경할 수 있으므로
원본이나 신규 작업본에 무조건 라이브러리 업데이트를 적용하지 않는다.

### VGA 네트 이름 차이

두 parity 경고는 다음과 같다:

| 패드 | PCB 네트 | 회로도 네트 |
| --- | --- | --- |
| U7.3 | `/Control Logic/~{VGA_TRY}` | `/Control Logic/~{VGA_WIN}` |
| U1.9 | `/Control Logic/~{VGA_TRY}` | `/Control Logic/~{VGA_WIN}` |

회로도 XML netlist export에서도 VGA_WIN의 노드는 U7.3과 U1.9로 확인했다.
동일한 두 패드의 이름 변경 흔적으로 보이지만, 이름만 바꾸기 전 신규 작업본에서
PCB의 실제 pad/net·배선 연결을 대조해야 한다. 원본은 수정하지 않았다.

### 글꼴 경고

`C64 Pro`/`C64 Pro Mono` 미설치와 Fontconfig 경고가 로그에 남는다.
원본에 텍스트 크기/두께 제외 항목이 있으므로 대체 글꼴로 출력한 실크를 그대로
제조해도 된다는 뜻이 아니다. 신규 PCB에서 폰트와 실크 도형을 확정하고 재검사한다.

## 다음 설계 단계

1. 별도 통합 CAD 작업본에서 기존 symbol/footprint 차이와 위 네트 이름을 대조한다.
2. 기존 제외·비활성 규칙을 검토하고 신규 회로에 그대로 적용하지 않도록 한다.
3. I/O decode·음원·Attribute 회로의 논리/타이밍을 확정한다.
4. 회로도에 구현하고 ERC/netlist 대조 후 PCB 배치·배선을 진행한다.

현재 산출물에는 여전히 신규 통합 회로도, 배선 PCB, 제조 Gerber가 없다.
