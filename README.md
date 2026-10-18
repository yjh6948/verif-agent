# verif-agent: 시뮬레이션 실패를 LLM이 고치는 RTL 검증 루프

RTL 검증은 IC 개발 기간의 큰 몫을 차지하고 최근에는 LLM으로 assertion과 testbench를 만들거나 버그를 고치는 연구(UCAgent·AssertLLM·ChatSVA 등)가 나오고 있습니다. 그 흐름을 개인 프로젝트 규모로 줄여 직접 만들어 본 Python 스크립트입니다.

```
시뮬레이션 실행 (iverilog + vvp)
   └ 통과 → 종료
   └ 실패 → RTL 소스 + 실패 로그를 Claude Code CLI(headless)에 전달
            → 수정본으로 RTL 교체 → 다시 시뮬레이션   (최대 N회)
```

- 통과 판정: 로그에 `ALL TESTS PASSED`가 있고 `FAIL`과 `ERROR`가 없을 때. 기능 테스트가 다 통과해도 assertion 에러가 하나라도 있으면 실패로 봅니다.
- 원본 RTL은 시작할 때 `.orig_backup`으로 복사해 둡니다.
- testbench는 건드리지 않습니다. 모델이 고칠 수 있는 건 RTL 파일 하나뿐입니다.

## 실행 결과

[axi_lite_slave](https://github.com/yjh6948/axi_lite_slave)에 BRESP를 매 클럭 뒤집는 버그를 넣은 사본으로 돌렸습니다. 버그 줄에 힌트가 될 주석은 지우고 실행했습니다. 전체 로그는 [examples/axi_bresp_run.log](examples/axi_bresp_run.log)에 있습니다.

```
[agent] --- attempt 1/3: running simulation ---
ERROR: axi_lite_slave.v:212: [ASSERT] BVALID/BRESP changed while waiting for BREADY
ERROR: axi_lite_slave.v:212: [ASSERT] BVALID/BRESP changed while waiting for BREADY
ERROR: axi_lite_slave.v:212: [ASSERT] BVALID/BRESP changed while waiting for BREADY
ALL TESTS PASSED
[agent] simulation failed. Asking claude for a fix (attempt 1)...
[agent] --- attempt 2/3: running simulation ---
ALL TESTS PASSED
[agent] PASSED on attempt 2. Done.
```

모델이 바꾼 건 주입한 2줄을 지운 것뿐이었습니다.

```diff
-            end else if (s_axi_bvalid && !s_axi_bready) begin
-                s_axi_bresp  <= ~s_axi_bresp;
```

## 한계

- 버그 1개로 확인한 결과입니다. 여러 버그 유형에서 성공률을 잰 건 아닙니다.
- assertion 메시지가 "BRESP가 바뀌었다"고 직접 말해 주기 때문에 모델 입장에서 쉬운 문제였습니다. 이 루프가 잘 돈 건 assertion을 먼저 제대로 써 둔 덕이 큽니다.
- 연구용 시스템과 달리 coverage DB나 파인튜닝 모델이나 강화학습이 없습니다. LLM 하나를 횟수 제한을 건 루프에 넣은 수준입니다.
- Windows에서 `claude.cmd`를 띄우려고 `shell=True`를 씁니다. 이 부분과 경로 처리에서 생긴 문제 2건을 직접 디버깅했습니다.

## 실행

```bash
# 필요: iverilog/vvp, 로그인된 claude CLI
python verif_agent.py --rtl path/to/dut.v --tb path/to/tb.v --max-iters 3
```
