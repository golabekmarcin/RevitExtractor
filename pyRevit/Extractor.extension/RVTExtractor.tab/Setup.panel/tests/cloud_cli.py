# -*- coding: utf-8 -*-
"""CPython helper for run_extractor_integration.ps1 -Cloud (specs/SPEC-cloud-catalog.md, criterion 14).

  fixture --base B --sample S --year Y --out F
        builds a fake Revit profile under B (all synthetic): a cache tree with the sample model
        saved under GUID file names, a synthetic journal, the name memory; runs the real
        rx_cloud.scan and rx_cloud.plan_stage; writes the fixture description to F (JSON)
  run   --fixture F --revit-dir R --year Y --output-parent O
        queues the staged job on rx_runner.Queue (the same code the Export button uses), runs
        it until the queue is idle and prints the outcome as JSON

Output is ASCII JSON (non-ASCII escaped). Errors: exit code 2 and {"error": "..."}.
Everything is written under B and O, which the caller puts in %TEMP%. The cache copies are only
read. Every GUID is a repeated-digit synthetic one.
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert

import rx_cloud  # noqa: E402
import rx_runner  # noqa: E402
from rx_capabilities import for_revit  # noqa: E402
from rx_index import build_index  # noqa: E402

ACCOUNT = "99999999"
PROJECT = "11111111-1111-1111-1111-111111111111"
HOST = "33333333-3333-3333-3333-333333333333"
LINK = "44444444-4444-4444-4444-444444444444"
ABSENT = "55555555-5555-5555-5555-555555555555"
PROJECT_NAME = "Demo Tower"
HOST_NAME = u"Przykład-Zażółć.rvt"   # Polish letters on purpose
LINK_NAME = "Beta-MEP"                                            # no .rvt: it is added
ABSENT_NAME = "Gamma-Absent.rvt"

_JOURNAL = u"""' 0:< Journal started for the synthetic fixture
         ModelPath Created: Is server path = True, Region = "US", Central server = "", Path = "CLD:\\\\US\\\\{%(p)s}%(pn)s\\\\{%(h)s}%(hn)s"
         ModelPath Created: Is server path = True, Region = "US", Central server = "", Path = "CLD:\\\\US\\\\{%(p)s}%(pn)s\\\\{%(l)s}%(ln)s.rvt"
"""


def _copy(src, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)


def build_fixture(base, sample, year, now=None):
    """The fake profile under `base`; returns the fixture description (JSON-safe dict)."""
    folders = rx_cloud.revit_folders(base, year)
    project_dir = os.path.join(folders["cache"], ACCOUNT, PROJECT)
    host_file = os.path.join(project_dir, HOST + ".rvt")
    link_file = os.path.join(project_dir, "LinkedModels", LINK + ".rvt")
    _copy(sample, host_file)
    _copy(sample, link_file)
    os.makedirs(folders["journals"], exist_ok=True)
    journal = os.path.join(folders["journals"], "journal.0001.txt")
    text = _JOURNAL % {"p": PROJECT, "pn": PROJECT_NAME, "h": HOST, "hn": HOST_NAME,
                       "l": LINK, "ln": LINK_NAME}
    with open(journal, "w", encoding="utf-8", newline="\r\n") as handle:
        handle.write(text)
    memory = rx_cloud.Memory(os.path.join(base, "cloud-catalog.json")).load()
    memory.set_included([rx_cloud.project_key(ACCOUNT, PROJECT)])
    catalog = None
    for step in rx_cloud.scan(folders, memory, time.time() if now is None else now):
        catalog = step
    rows = [row for row in catalog.rows if row.model_guid == HOST]
    if len(rows) != 1 or not rows[0].enabled:
        raise ValueError("the fake catalog did not list the host model")
    row = rows[0]
    cache_files = list(rx_cloud.scan_cache(folders["cache"]))
    link_refs = [{"name": LINK_NAME, "project_guid": PROJECT, "model_guid": LINK},
                 {"name": ABSENT_NAME, "project_guid": PROJECT, "model_guid": ABSENT}]
    plan = rx_cloud.plan_stage(row, link_refs, cache_files, memory)
    stage = {"items": [{"src": item.src, "name": item.name, "size": item.size, "mtime": item.mtime}
                       for item in plan.items], "notes": list(plan.notes)}
    return {"base": base, "year": year, "model_name": row.name, "model_key": row.key,
            "cache_path": row.cache_path, "stage": stage,
            "cache_files": [item.path for item in cache_files],
            "counts": {"named_rows": len(catalog.rows), "projects": len(catalog.projects),
                       "cache_files": len(cache_files), "items": len(plan.items),
                       "notes": len(plan.notes)}}


class _Handle(object):
    def __init__(self, process):
        self.process, self.pid = process, process.pid

    def has_exited(self):
        return self.process.poll() is not None

    def exit_code(self):
        return self.process.poll()

    def wait(self, milliseconds):
        try:
            self.process.wait(milliseconds / 1000.0)
            return True
        except subprocess.TimeoutExpired:
            return False

    def close(self):
        pass


class Starter(object):
    """The fields rx_runner.DotNetStarter sets: file, arguments, working dir, environment."""

    def start(self, spec, show_window=False):
        env = dict(os.environ)
        env.update(spec.env)
        line = '"%s" %s' % (spec.file, spec.arguments)
        return _Handle(subprocess.Popen(line, cwd=spec.working_dir, env=env,
                                        creationflags=0x08000000))   # CREATE_NO_WINDOW

    def run(self, spec):
        return subprocess.call('"%s" %s' % (spec.file, spec.arguments),
                               creationflags=0x08000000)


def tree_running():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return "revitextractor" in out.lower()


def run_staged(fixture, revit_dir, year, output_parent, starter=None, tree_running=tree_running,
               timeout=1800):
    index = build_index(for_revit(year))
    queue = rx_runner.Queue(starter or Starter(), datetime.datetime.now,
                            system_root=rx_runner.default_system_root(), tree_running=tree_running)
    job = rx_runner.Job(fixture["cache_path"], index, revit_dir, output_parent,
                        stage=fixture["stage"], model_name=fixture["model_name"],
                        model_key=fixture["model_key"])
    queue.add(job)
    states, start = [], time.time()
    worst_poll = 0.0
    while queue.busy() and time.time() - start < timeout:
        began = time.perf_counter()
        queue.poll()
        if job.state == "staging":
            worst_poll = max(worst_poll, time.perf_counter() - began)
        if not states or states[-1] != job.state:
            states.append(job.state)
        time.sleep(0.2 if job.state == "staging" else 1.0)
    timed_out = queue.busy()
    root = job.paths.root if job.paths else None
    model_dir = os.path.join(root, rx_runner.STAGE_FOLDER) if root else None
    listing = sorted(os.listdir(model_dir)) if model_dir and os.path.isdir(model_dir) else []
    record = None
    if "stage.json" in listing:
        with open(os.path.join(model_dir, "stage.json"), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    return {"state": job.state, "message": job.result.message if job.result else None,
            "success_jobs": getattr(job.result, "success_jobs", None) if job.result else None,
            "failed_jobs": getattr(job.result, "failed_jobs", None) if job.result else None,
            "states": states, "cleanup": job.cleanup, "timed_out": timed_out,
            "worst_staging_poll_ms": round(worst_poll * 1000, 1), "root": root,
            "model_dir": listing, "stage_record_items": len(record["items"]) if record else 0,
            "has_bubble": bool(root) and os.path.isfile(
                os.path.join(root, "output", "bubble.json")),
            "elapsed_seconds": round(time.time() - start, 1)}


def main(argv):
    parser = argparse.ArgumentParser(prog="cloud_cli.py")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixture")
    fixture.add_argument("--base", required=True)
    fixture.add_argument("--sample", required=True)
    fixture.add_argument("--year", required=True, type=int)
    fixture.add_argument("--out", required=True)
    run = commands.add_parser("run")
    run.add_argument("--fixture", required=True)
    run.add_argument("--revit-dir", required=True)
    run.add_argument("--year", required=True, type=int)
    run.add_argument("--output-parent", required=True)
    run.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        if args.command == "fixture":
            data = build_fixture(os.path.abspath(args.base), args.sample, args.year)
            with open(args.out, "w", encoding="ascii") as handle:
                handle.write(json.dumps(data, ensure_ascii=True, sort_keys=True))
            data = {"counts": data["counts"], "cache_files": data["cache_files"]}
        else:
            with open(args.fixture, "r", encoding="ascii") as handle:
                data = run_staged(json.load(handle), args.revit_dir, args.year,
                                  os.path.abspath(args.output_parent), timeout=args.timeout)
    except (rx_runner.RunnerError, ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
