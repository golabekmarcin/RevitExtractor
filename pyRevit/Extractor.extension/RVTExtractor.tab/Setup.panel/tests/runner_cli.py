# -*- coding: utf-8 -*-
"""CPython helper for run_extractor_integration.ps1: rx_runner as JSON on stdout.

  plan      --output-parent P --revit-dir R --model M --year Y [--system-root S]
            creates a new run folder with the default index for that year and prints the
            run paths and the launch spec (the exact spec the queue would start)
  check     --root R --exit-code N      success check of a finished run (read-only)
  progress  --root R                    last meaningful console.log line (read-only)
  kill-spec --pid N [--system-root S]   the cancel command for a pid

Output is ASCII JSON (non-ASCII escaped), so Windows PowerShell 5.1 reads it intact.
Errors: exit code 2 and {"error": "..."}.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert

import rx_runner  # noqa: E402
from rx_capabilities import for_revit  # noqa: E402
from rx_index import build_index  # noqa: E402


def run_paths(root):
    root = os.path.abspath(root)
    return rx_runner.RunPaths(root=root, index=os.path.join(root, "index.json"),
                              output=os.path.join(root, "output"),
                              logs=os.path.join(root, "logs"),
                              journals=os.path.join(root, "journals"),
                              console=os.path.join(root, "console.log"),
                              stderr=os.path.join(root, "stderr.log"))


def command_plan(args):
    system_root = args.system_root or rx_runner.default_system_root()
    index = build_index(for_revit(args.year))
    paths = rx_runner.plan_run(args.output_parent, datetime.datetime.now(),
                               rx_runner.new_token())
    exe = rx_runner.extractor_exe(args.revit_dir)
    # Same order as Queue._start: validate the spec before anything is created on disk.
    spec = rx_runner.launch_spec(exe, args.revit_dir, args.model, paths, system_root)
    rx_runner.prepare_run(paths, index)
    return {"paths": paths._asdict(), "spec": spec._asdict(), "index": index}


def command_check(args):
    paths = run_paths(args.root)
    result = rx_runner.check_result(
        args.exit_code, rx_runner._read_text(paths.console),
        os.path.isfile(os.path.join(paths.output, "bubble.json")),
        os.path.isdir(os.path.join(paths.output, "Resource")))
    data = result._asdict()
    data["progress"] = command_progress(args)["progress"]
    return data


def command_progress(args):
    paths = run_paths(args.root)
    tail = rx_runner._read_text(paths.console, rx_runner._PROGRESS_TAIL_BYTES)
    return {"progress": rx_runner.progress_line(tail)}


def command_kill_spec(args):
    system_root = args.system_root or rx_runner.default_system_root()
    return rx_runner.kill_spec(args.pid, system_root)._asdict()


def main(argv):
    parser = argparse.ArgumentParser(prog="runner_cli.py")
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--output-parent", required=True)
    plan.add_argument("--revit-dir", required=True)
    plan.add_argument("--model", required=True)
    plan.add_argument("--year", required=True, type=int)
    plan.add_argument("--system-root")
    check = commands.add_parser("check")
    check.add_argument("--root", required=True)
    check.add_argument("--exit-code", required=True, type=int)
    progress = commands.add_parser("progress")
    progress.add_argument("--root", required=True)
    kill = commands.add_parser("kill-spec")
    kill.add_argument("--pid", required=True, type=int)
    kill.add_argument("--system-root")
    args = parser.parse_args(argv)
    handlers = {"plan": command_plan, "check": command_check, "progress": command_progress,
                "kill-spec": command_kill_spec}
    try:
        data = handlers[args.command](args)
    except (rx_runner.RunnerError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
