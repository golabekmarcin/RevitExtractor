# -*- coding: utf-8 -*-
"""CPython helper for run_extractor_integration.ps1: rx_runner as JSON on stdout.

  plan      --output-parent P --revit-dir R --model M --year Y [--system-root S]
            creates a new run folder with the default index for that year and prints the
            run paths and the launch spec (the exact spec the queue would start)
  check     --root R --exit-code N      success check of a finished run (read-only)
  progress  --root R                    last meaningful console.log line (read-only)
  kill-spec --pid N [--system-root S]   the cancel command for a pid
  analyzer-plan --output O              rx_status.analyzer_plan for a finished run's output
            folder, with this machine's PATH, file version of node.exe and a free port, plus
            what was found (node, its major version, server.mjs, packages). Starts nothing.
  status-sample --lang en|pl            the status window's text table and sample rows
            (job_view of made-up jobs), for preview_windows.ps1
  export-sample --lang en|pl            the Export button's model and view windows, driven by
            their real code with the WPF fakes of test_export_button.py (made-up models and
            views): text table, rows and each named control's text/check/enabled/visible state
  name      RUN [--template T] [--split]   rx_naming.NamedRun to the end on a real run folder
            (RUN = the folder holding output\\ and index.json, or its output\\), real hard links;
            default template "{OriginalName} {Date}". Prints counts only (no name or path).
            Exit 0 only when the state is done, output\\ is unchanged (size, mtime, SHA-256 of
            every file) and at least one item was named; 1 otherwise.

Output is ASCII JSON (non-ASCII escaped), so Windows PowerShell 5.1 reads it intact.
Errors: exit code 2 and {"error": "..."}.
"""
import argparse
import datetime
import json
import os
import socket
import sys
import types
from pathlib import Path

LIB = Path(__file__).resolve().parents[3] / "lib"
if str(LIB) not in sys.path:
    sys.path.append(str(LIB))  # append, never insert

import rx_runner  # noqa: E402
import rx_status  # noqa: E402
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


def output_snapshot(folder):
    """{relative path: (size, mtime_ns, sha256)} of every file under `folder`."""
    import hashlib
    out = {}
    for dirpath, _, files in os.walk(folder):
        for name in files:
            path = os.path.join(dirpath, name)
            st = os.stat(path)
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(2 ** 20), b""):
                    digest.update(chunk)
            out[os.path.relpath(path, folder)] = (st.st_size, st.st_mtime_ns, digest.hexdigest())
    return out


def command_name(args):
    """rx_naming.NamedRun to the end on a real run folder, with the real hard-link function.
    Prints counts only: no name or path of the model, the run or its files."""
    import rx_naming
    root = os.path.abspath(args.run)
    if os.path.basename(root).lower() == "output" and \
            os.path.isfile(os.path.join(os.path.dirname(root), "index.json")):
        root = os.path.dirname(root)
    paths = run_paths(root)
    if not os.path.isdir(paths.output) or not os.path.isfile(paths.index):
        raise ValueError("not a run folder (needs output\\ and index.json)")
    now = datetime.datetime.now()
    naming = {"template": args.template, "values": None, "split": args.split,
              "system": rx_naming.system_values(now, "user", "user", "Sample", "short", "long")}
    before = output_snapshot(paths.output)
    run = rx_naming.NamedRun(paths, naming)
    for _ in run.steps():
        pass
    after = output_snapshot(paths.output)
    named = os.path.join(root, "named")
    kinds = {}
    for entry in run.items:
        kind = "view" if entry["kind"] == "dir" else \
            os.path.splitext(entry["source"])[1].lstrip(".").lower()
        kinds[kind] = kinds.get(kind, 0) + 1
    longest, on_disk = 0, 0
    for dirpath, dirs, files in os.walk(named):
        for child in dirs + files:
            on_disk += 1
            longest = max(longest, len(os.path.join(dirpath, child)))
    links = []
    for entry in run.items:
        if entry["mode"] != "linked":
            continue
        target = os.path.join(named, *entry["name"].split("/"))
        if os.path.isfile(target):
            links.append(os.stat(target).st_nlink)
        for dirpath, _, files in os.walk(target):
            links.extend(os.stat(os.path.join(dirpath, f)).st_nlink for f in files)
    unchanged = before == after
    made = run.counts["linked"] + run.counts["copied"]
    data = {"state": run.state, "counts": run.counts, "items_by_kind": kinds,
            "named_entries_on_disk": on_disk, "linked_files_checked": len(links),
            "links_verified": bool(links) and all(n >= 2 for n in links),
            "longest_named_path": longest, "output_unchanged": unchanged,
            "output_files_compared": len(before), "notes": len(run.notes)}
    ok = run.state == "done" and unchanged and made > 0
    return data, (0 if ok else 1)


def command_kill_spec(args):
    system_root = args.system_root or rx_runner.default_system_root()
    return rx_runner.kill_spec(args.pid, system_root)._asdict()


def file_major(path):
    """FileMajorPart of a file's version resource (what rx_status_ui.node_major reads in .NET)."""
    import ctypes
    from ctypes import wintypes
    version = ctypes.WinDLL("version")
    version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.c_void_p)
    version.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                            ctypes.c_void_p)
    version.VerQueryValueW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.POINTER(wintypes.UINT))
    size = version.GetFileVersionInfoSizeW(path, None)
    if not size:
        raise OSError("no version resource: " + path)
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(path, 0, size, data):
        raise OSError("cannot read the version of " + path)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        raise OSError("no fixed version info: " + path)
    fixed = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 4)).contents  # VS_FIXEDFILEINFO
    return int(fixed[2] >> 16)  # dwFileVersionMS high word


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def command_analyzer_plan(args):
    plan = rx_status.analyzer_plan(args.output, str(LIB), os.environ, os.path.isfile, file_major,
                                   free_port)
    node = rx_status._find_node(os.environ, os.path.isfile)
    try:
        major = file_major(node) if node else None
    except OSError:
        major = None
    analyzer = rx_status.analyzer_dir(str(LIB))
    found = {"node": node, "node_major": major, "analyzer": analyzer,
             "server": os.path.isfile(os.path.join(analyzer, "server.mjs")),
             "packages": os.path.isfile(os.path.join(analyzer, "node_modules", "pdfjs-dist",
                                                     "build", "pdf.mjs"))}
    if plan[0] == "local":
        return {"kind": "local", "spec": plan[1]._asdict(), "url": plan[2], "found": found}
    return {"kind": "web", "reason": plan[1], "found": found}


def polish_modules():
    """pyRevit set to Polish, for rx_i18n.tr (same resolver shape as the tests use)."""
    def get_locale_string(string_dict):
        return string_dict.get("pl") or string_dict.get("en_us")
    applocales = types.SimpleNamespace(get_locale_string=get_locale_string)
    coreutils = types.SimpleNamespace(applocales=applocales)
    return {"pyrevit": types.SimpleNamespace(coreutils=coreutils),
            "pyrevit.coreutils": coreutils, "pyrevit.coreutils.applocales": applocales}


def sample_views(now):
    """Made-up jobs in every state the window shows (no client data)."""
    base = os.path.join("C:\\", "Projects", "Sample")
    exports = os.path.join("C:\\", "Users", "user", "Documents", "RevitExtractor")
    revit = os.path.join("C:\\", "Program Files", "Autodesk", "Revit")
    index = {"metadata": {"parameters": {"derivative_type": {}}}}
    minute = datetime.timedelta(minutes=1)

    def job(name, state, started=None, ended=None, message=None, with_paths=True, cancel=False):
        item = rx_runner.Job(os.path.join(base, name), index, revit, exports)
        item.id = name
        item.state = state
        item.started_at = started
        item.ended_at = ended
        item.cancel_requested = cancel
        if message is not None:
            item.result = rx_runner.Result(state, None, None, message)
        if with_paths:
            item.paths = rx_runner.plan_run(exports, started or now, "a1b2c3d4")
        return item

    ok = rx_runner.check_result(0, "Success Jobs: 13, Failed Jobs: 0", True, True).message
    failed = rx_runner.check_result(1, "", False, False).message
    cancelled = rx_status.tr("Export cancelled.", "Eksport anulowany.")
    rows = [
        (job("DynamoSample.rvt", "ok", now - 9 * minute, now - 7 * minute, ok), None, None),
        (job("Library - imperial.rvt", "failed", now - 7 * minute, now - 6 * minute, failed),
         None, None),
        (job("Office tower - structure.rvt", "cancelled", now - 6 * minute, now - 5 * minute,
             cancelled), None, None),
        (job("Office tower - architecture.rvt", "running", now - 4 * minute - datetime.timedelta(
            seconds=12)), {"task": "Export SVF For 3D Views. Views Count: 4",
                           "status": "completed", "percent": 30}, None),
        (job("Site plan.rvt", "queued", with_paths=False), None, 1),
        (job("Housing block A.rvt", "queued", with_paths=False), None, 2),
    ]
    return [rx_status.job_view(item, info, now, position) for item, info, position in rows]


def command_status_sample(args):
    saved = dict(sys.modules)
    try:
        if args.lang == "pl":
            sys.modules.update(polish_modules())
        now = datetime.datetime(2026, 11, 11, 10, 30, 0)
        views = sample_views(now)
        error = rx_status.tr(
            "The local Analyzer is not available: {0} The output folder and the website were "
            "opened instead.",
            "Lokalny Analyzer jest niedostępny: {0} Zamiast niego otwarto folder output i stronę "
            "internetową.").format(rx_status.tr("Node.js was not found.",
                                                "Nie znaleziono Node.js."))
        return {"resources": rx_status.resources(), "views": views,
                "summary": rx_status.summary(views), "hint": rx_status.queue_hint(views),
                "error": error, "selected": 0}
    finally:
        for key in list(sys.modules):
            if key not in saved:
                del sys.modules[key]
        sys.modules.update(saved)


def _control_state(window, names):
    """Text, IsChecked, IsEnabled and Visibility of the fake window's named controls."""
    state = {}
    for name in names:
        control = getattr(window, name)
        entry = {"enabled": bool(control.IsEnabled),
                 "visible": getattr(control, "Visibility", "Visible") != "Collapsed"}
        if isinstance(control.Text, str) and control.Text:
            entry["text"] = control.Text
        if name.endswith(("_cb", "_rb")):
            entry["checked"] = bool(control.IsChecked)
        state[name] = entry
    return state


def _cloud_sample(kit, caps, settings, base):
    """The model window on its Cloud source: made-up projects, models and dates (the invented
    names of the tests, repeated-digit GUIDs), driven by the real code."""
    import shutil
    import tempfile
    folder = tempfile.mkdtemp(prefix="rx-cloud-sample-")
    try:
        memory = kit.cloud_memory(folder)
        memory.set_included([kit.CP1_KEY])
        files = kit.cloud_cache_files()
        cloud = {"folders": {"cache": kit.CACHE_ROOT, "journals": base}, "memory": memory,
                 "scan": kit.FakeCloudScan(files), "scan_cache": lambda root: list(files),
                 "now": lambda: kit.CNOW}
        window = kit.EXPORT_UI.ModelWindow(
            caps, dict(settings, roots=[]), None, object(), None, lambda values: None,
            extractor_build="2025.3.0.12", scan=kit.FakeScan([]), clock=kit.StepClock(0.0),
            cloud=cloud)
        window.show_dialog()
        window.source_local_rb.IsChecked = False
        window.source_cloud_rb.IsChecked = True
        window.source_cloud_rb.Checked.fire(window.source_cloud_rb, None)
        while kit.TIMERS[-1].IsEnabled:
            kit.TIMERS[-1].Tick.fire(kit.TIMERS[-1], None)
        for row in window._cloud_rows:
            if row.Name == "Alpha-Architecture.rvt":
                row.set_quietly(True)
        window._refresh_state()
        return {
            "rows": [{"Checked": row.Checked, "Name": row.Name, "Project": row.Project,
                      "CacheDate": row.CacheDate, "Note": row.Note, "Enabled": row.Enabled,
                      "Tip": row.Tip} for row in window._cloud_rows],
            "projects": [{"Checked": project.Checked, "Label": project.Label,
                          "Tip": project.Tip} for project in window.cloud_projects_lb.ItemsSource],
            "roots": [],
            "controls": _control_state(window, kit.xaml_names(kit.MODELS_XAML)),
        }
    finally:
        shutil.rmtree(folder, True)


def command_export_sample(args):
    """The Export button's windows driven by their real code (rx_export_ui.py) with the WPF
    fakes of test_export_button.py: made-up models and views, no client data."""
    saved = dict(sys.modules)
    try:
        if args.lang == "pl":
            sys.modules.update(polish_modules())
        import test_export_button as kit
        import rx_catalog
        caps = for_revit(2022)
        base = os.path.join("C:\\", "Projects", "Sample")
        server = os.path.join("\\\\fileserver", "bim", "Housing")
        facts = [
            (base, "Office tower - architecture.rvt", {"format": "2022", "is_workshared": True}),
            (base, "Office tower - structure.rvt", {"format": "2022"}),
            (base, "Office tower - MEP.rvt", {"format": "2021"}),
            (base, "Office tower - MEP_user.rvt", {"format": "2022", "is_local": True}),
            (server, "Housing block A.rvt", {"format": "2024"}),
            (server, "Housing block B.rvt", {"error": "IOException"}),
            (server, "Site plan.rvt", {"format": "2022"}),
        ]
        rows = [rx_catalog._make_row(os.path.join(folder, name), info, caps.year)
                for folder, name, info in facts]
        kit.reset_fakes()
        settings = {"roots": [base, server],
                    "output_parent": os.path.join("C:\\", "Users", "user", "Documents",
                                                  "RevitExtractor"),
                    "max_parallel": 1, "shared_index_path": ""}
        models = kit.EXPORT_UI.ModelWindow(
            caps, settings, None, object(), None, lambda values: None,
            extractor_build="2025.3.0.12", scan=kit.FakeScan(rows), clock=kit.StepClock(0.0))
        models.show_dialog()
        kit.TIMERS[-1].Tick.fire(kit.TIMERS[-1], None)
        for row in models._rows:
            if row.Name in ("Office tower - architecture.rvt", "Office tower - MEP.rvt"):
                row.set_quietly(True)
        models._refresh_state()
        model_rows = [{"Checked": row.Checked, "Name": row.Name, "Folder": row.Folder,
                       "Version": row.Version, "Note": row.Note, "Enabled": row.Enabled,
                       "Tip": row.Tip} for row in models._rows]

        cloud = _cloud_sample(kit, caps, settings, base)

        def record(element_id, name, kind):
            return {"id": str(element_id), "uid": "uid-%d" % element_id, "name": name,
                    "kind": kind, "search": " ".join((name, kind, str(element_id))).lower()}
        kinds = rx_status.tr("Floor plans", "Rzuty kondygnacji"), \
            rx_status.tr("Sheets", "Arkusze"), rx_status.tr("3D views", "Widoki 3D")
        snapshot = {
            "title": "Office tower - MEP.rvt", "path": os.path.join(base, "Office tower - MEP.rvt"),
            "views_2d": [record(312, "Level 1", kinds[0]), record(313, "Level 2", kinds[0]),
                         record(401, "M-101 - Ventilation, level 1", kinds[1]),
                         record(402, "M-102 - Ventilation, level 2", kinds[1])],
            "views_3d": [record(20, "{3D}", kinds[2]), record(21, "Coordination", kinds[2])],
            "ifc_setups": [], "ifc_error": ""}
        note = [row.Note for row in models._rows if row.Name == "Office tower - MEP.rvt"][0]
        views = kit.EXPORT_UI.ViewWindow(snapshot, caps, note=note, save_dir=base)
        views.default2d_rb.IsChecked = False
        views.selected2d_rb.IsChecked = True
        for row in views._rows["2d"]:
            if row.Kind == kinds[1]:
                row.set_quietly(True)
        views._on_settings_changed(None, None)
        view_rows = {dimension: [{"Checked": row.Checked, "Name": row.Name, "Kind": row.Kind,
                                  "ElementId": row.ElementId} for row in views._rows[dimension]]
                     for dimension in ("2d", "3d")}
        return {
            "resources": kit.load_text_module().resources(),
            "models": {"rows": model_rows, "roots": list(models.roots_lb.ItemsSource),
                       "controls": _control_state(models, kit.xaml_names(kit.MODELS_XAML))},
            "cloud": cloud,
            "views": {"rows": view_rows,
                      "controls": _control_state(views, kit.xaml_names(kit.VIEWS_XAML))},
        }
    finally:
        for key in list(sys.modules):
            if key not in saved:
                del sys.modules[key]
        sys.modules.update(saved)


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
    analyzer = commands.add_parser("analyzer-plan")
    analyzer.add_argument("--output", required=True)
    sample = commands.add_parser("status-sample")
    sample.add_argument("--lang", choices=("en", "pl"), default="en")
    export_sample = commands.add_parser("export-sample")
    export_sample.add_argument("--lang", choices=("en", "pl"), default="en")
    name = commands.add_parser("name")
    name.add_argument("run")
    name.add_argument("--template", default="{OriginalName} {Date}")
    name.add_argument("--split", action="store_true")
    args = parser.parse_args(argv)
    handlers = {"plan": command_plan, "check": command_check, "progress": command_progress,
                "kill-spec": command_kill_spec, "analyzer-plan": command_analyzer_plan,
                "status-sample": command_status_sample, "export-sample": command_export_sample,
                "name": command_name}
    code = 0
    try:
        data = handlers[args.command](args)
        if args.command == "name":
            data, code = data
    except (rx_runner.RunnerError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(data, ensure_ascii=True, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
