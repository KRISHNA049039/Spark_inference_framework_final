"""
extract_api.py - read the repository's source and produce docs/tdd/api.json:
every module's docstring, classes, functions (signature, docstring, line),
argparse options, environment variables, and a file inventory. The TDD
builder (build_tdd_docx.js) uses it for the API reference, the CLI and config
reference, and for exact file:line references in the request traces.

  python docs/tdd/extract_api.py
"""
import ast
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {"results", "debs", "node_modules", "cdk.out", ".git", "__pycache__", "wheels", "wheels-hotfix", "weights"}
CODE_EXT = {".py", ".sh", ".ps1", ".js", ".yml", ".yaml", ".json", ".txt"}
FRAMEWORK = ("submit_job.py", "submit_pipeline_job.py", "inference/", "models/", "data/", "monitoring/")
TOOLING = ("benchmark/", "docs/")


def category(rel):
    if rel.startswith(FRAMEWORK):
        return "framework"
    if rel.startswith("deploy/") or rel.startswith("Dockerfile") or os.path.basename(rel).startswith("Dockerfile"):
        return "deployment"
    if rel.startswith("benchmark/") and os.path.basename(rel) in (
            "run_benchmark.py", "cluster_benchmark.py", "spark_vs_single_gpu.py", "incremental_load_test.py",
            "quick_compare.py", "capture_spark_stats.py", "run_all_cpu_tests.ps1", "__init__.py"):
        return "benchmark"
    if rel.startswith(TOOLING):
        return "tooling"
    return "other"


def sig(fn):
    a = fn.args
    parts = []
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for arg, d in zip(pos, defaults):
        s = arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else "")
        if d is not None:
            s += f" = {ast.unparse(d)}"
        parts.append(s)
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        s = arg.arg + (f": {ast.unparse(arg.annotation)}" if arg.annotation else "")
        if d is not None:
            s += f" = {ast.unparse(d)}"
        parts.append(s)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    ret = f" -> {ast.unparse(fn.returns)}" if fn.returns else ""
    return f"({', '.join(parts)}){ret}"


def doc1(node):
    d = ast.get_docstring(node) or ""
    para = d.strip().split("\n\n")[0]
    return " ".join(para.split())


def py_info(path, rel):
    src = open(path, encoding="utf-8", errors="replace").read()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return {"error": str(e)}
    info = {"doc": doc1(tree), "classes": [], "functions": [], "cli": [], "env": [], "imports": []}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            c = {"name": node.name, "line": node.lineno, "bases": [ast.unparse(b) for b in node.bases], "doc": doc1(node), "methods": []}
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    c["methods"].append({"name": m.name, "line": m.lineno, "sig": sig(m), "doc": doc1(m)})
            info["classes"].append(c)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            f = {"name": node.name, "line": node.lineno, "end": node.end_lineno, "sig": sig(node), "doc": doc1(node), "nested": []}
            for sub in ast.walk(node):
                if sub is not node and isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    f["nested"].append({"name": sub.name, "line": sub.lineno})
            info["functions"].append(f)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = node.module if isinstance(node, ast.ImportFrom) else ",".join(a.name for a in node.names)
            if mod and mod.split(".")[0] in ("inference", "models", "data", "monitoring", "benchmark"):
                info["imports"].append(mod)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument" and node.args:
            opts = [a.value for a in node.args if isinstance(a, ast.Constant)]
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg in ("default", "choices", "type", "help", "action", "required")}
            if "help" in kw:
                try:
                    kw["help"] = " ".join(str(ast.literal_eval(ast.parse(kw["help"], mode="eval").body)).split())
                except Exception:
                    pass
            info["cli"].append({"opts": opts, "line": node.lineno, **kw})
    for m in re.finditer(r'(?:environ(?:\.get)?\(|environ\[|getenv\()\s*"([A-Z0-9_]+)"', src):
        line = src[:m.start()].count("\n") + 1
        info["env"].append({"name": m.group(1), "line": line})
    return info


def main():
    files = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            ext = os.path.splitext(fn)[1]
            if not (ext in CODE_EXT or fn.startswith("Dockerfile")) or rel.startswith("docs/") and ext not in (".py", ".js"):
                continue
            if rel.startswith("models/pipelines/ner_translate/requirements") or rel.startswith("data/ner_samples"):
                continue
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            entry = {"path": rel, "lines": text.count("\n") + (0 if text.endswith("\n") else 1), "category": category(rel), "ext": ext or "dockerfile"}
            if ext == ".py":
                entry.update(py_info(p, rel))
            else:
                first = next((l.strip("#/ -=").strip() for l in text.splitlines()[:12]
                              if l.strip().startswith(("#", "//")) and len(l.strip("#/ -=").strip()) > 12), "")
                entry["doc"] = first
            files.append(entry)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api.json")
    json.dump({"root": ROOT, "files": files}, open(out, "w", encoding="utf-8"), indent=1)
    by = {}
    for f in files:
        by.setdefault(f["category"], [0, 0])
        by[f["category"]][0] += 1
        by[f["category"]][1] += f["lines"]
    print(out, {k: f"{v[0]} files / {v[1]} lines" for k, v in by.items()})


if __name__ == "__main__":
    main()
