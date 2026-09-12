#!/usr/bin/env python3
"""
verif_agent.py - a minimal self-repairing RTL verification loop.

Idea: run an Icarus Verilog simulation of an RTL module against its
testbench. If it fails, hand the RTL source and the failure log to an LLM
(here: the already-authenticated `claude` CLI in headless mode) and ask
for a corrected RTL file. Recompile and re-simulate. Repeat until the
testbench passes or a max-iteration budget is spent.

This is a scaled-down, personal-project version of research-grade
"agentic RTL verification" systems (e.g. UCAgent): same feedback loop
(simulate -> read failure -> patch -> re-simulate), no coverage database,
no fine-tuned model, no RL -- just a plain LLM in a loop with a hard
iteration cap so it can't run away.

Usage:
    python verif_agent.py --rtl path/to/dut.v --tb path/to/tb.v \
        --top tb_module_name [--max-iters 3]
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PASS_MARKER = "ALL TESTS PASSED"


def run_simulation(rtl_path: Path, tb_path: Path, sim_dir: Path) -> tuple[bool, str]:
    """Compile + run the testbench against the current RTL. Returns (passed, log)."""
    sim_dir.mkdir(parents=True, exist_ok=True)
    sim_bin = sim_dir / "sim.out"

    compile_cmd = ["iverilog", "-g2012", "-o", str(sim_bin), str(rtl_path), str(tb_path)]
    compile_result = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=60)
    if compile_result.returncode != 0:
        return False, "COMPILE FAILED:\n" + compile_result.stdout + compile_result.stderr

    run_result = subprocess.run(
        ["vvp", str(sim_bin)], capture_output=True, text=True, timeout=60
    )
    log = run_result.stdout + run_result.stderr
    passed = PASS_MARKER in log and "FAIL" not in log and "ERROR" not in log
    return passed, log


def ask_llm_for_fix(rtl_source: str, sim_log: str, rtl_filename: str) -> str:
    """Call the headless `claude` CLI and return its proposed fixed RTL source."""
    prompt = f"""You are fixing a bug in a Verilog RTL module so that its testbench passes.

Below is the current contents of {rtl_filename}, followed by the simulation
log from running it against its testbench (which failed).

Find the bug and fix it. Respond with ONLY the complete corrected Verilog
source for {rtl_filename} -- no markdown code fences, no explanation, no
commentary. Your entire response must be valid Verilog that can be written
directly to the file.

=== CURRENT RTL SOURCE ({rtl_filename}) ===
{rtl_source}

=== SIMULATION LOG (FAILURE) ===
{sim_log}
"""
    claude_bin = shutil.which("claude")
    if claude_bin is None:
        raise RuntimeError("claude CLI not found on PATH")

    result = subprocess.run(
        [claude_bin, "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,
        shell=True,  # needed on Windows to launch the claude.cmd shim
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed: {result.stderr}")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Self-repairing RTL verification loop")
    parser.add_argument("--rtl", required=True, type=Path, help="RTL source file to fix")
    parser.add_argument("--tb", required=True, type=Path, help="Testbench file (unmodified)")
    parser.add_argument("--max-iters", type=int, default=3, help="Max fix attempts")
    parser.add_argument(
        "--sim-dir", type=Path, default=Path("agent_sim"), help="Scratch dir for compiled sims"
    )
    args = parser.parse_args()

    rtl_path = args.rtl.resolve()
    tb_path = args.tb.resolve()
    backup_path = rtl_path.with_suffix(rtl_path.suffix + ".orig_backup")
    shutil.copy(rtl_path, backup_path)
    print(f"[agent] backed up original RTL to {backup_path}")

    for attempt in range(1, args.max_iters + 1):
        print(f"\n[agent] --- attempt {attempt}/{args.max_iters}: running simulation ---")
        passed, log = run_simulation(rtl_path, tb_path, args.sim_dir)
        print(log.strip())

        if passed:
            print(f"\n[agent] PASSED on attempt {attempt}. Done.")
            return 0

        if attempt == args.max_iters:
            print(f"\n[agent] FAILED after {args.max_iters} attempts. Giving up.")
            print(f"[agent] original RTL preserved at {backup_path}; "
                  f"last attempted fix left in place at {rtl_path}")
            return 1

        print(f"\n[agent] simulation failed. Asking claude for a fix (attempt {attempt})...")
        rtl_source = rtl_path.read_text(encoding="utf-8")
        try:
            fixed_source = ask_llm_for_fix(rtl_source, log, rtl_path.name)
        except RuntimeError as e:
            print(f"[agent] LLM call failed: {e}")
            return 1

        if not fixed_source:
            print("[agent] LLM returned an empty response. Giving up.")
            return 1

        rtl_path.write_text(fixed_source, encoding="utf-8")
        print(f"[agent] wrote candidate fix to {rtl_path}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
