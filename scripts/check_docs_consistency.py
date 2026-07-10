#!/usr/bin/env python3
"""Check repository-local documentation references without external requests.

The checker intentionally treats heuristic findings as warnings.  Its non-zero
exit status is reserved for Markdown links, anchors, explicit repo-root command
entrypoints, and documented API paths that can be disproved from tracked files.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOC_SUFFIXES = {".md", ".rst", ".txt"}
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
INLINE_PATH = re.compile(
    r"(?:python3?|bash)\s+((?:autoscale-source-split|k3s-migration-bundle-sanitized|monitoring-rebuild|config|scripts)/[^\s`|\\]+)"
)
API_PATH = re.compile(r"/(?:api/v1/)?[A-Za-z0-9_{}./-]+")


@dataclass(frozen=True)
class Finding:
    level: str
    document: Path
    line: int
    message: str


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    return [ROOT / item for item in output.splitlines()]


def github_anchor(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^\w\- ]", "", value)
    return re.sub(r"[ -]+", "-", value)


def document_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = github_anchor(match.group(1))
        count = counts.get(base, 0)
        counts[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def local_target(document: Path, target: str) -> tuple[Path | None, str | None]:
    target = unquote(target.strip().strip("<>"))
    target = target.split(" ", 1)[0]
    if target.startswith(("http://", "https://", "mailto:", "tel:")):
        return None, None
    path_text, separator, anchor = target.partition("#")
    if not path_text:
        return document, anchor if separator else None

    # Local file links emitted by this workspace may include a human line suffix.
    path_text = re.sub(r":\d+$", "", path_text)
    candidate = Path(path_text)
    if candidate.is_absolute():
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            return None, None
    else:
        candidate = document.parent / candidate
    return candidate.resolve(), anchor if separator else None


def router_paths(paths: list[Path]) -> set[str]:
    discovered = {"/", "/metrics"}
    for path in paths:
        if path.suffix != ".py" or "/app/routers/" not in path.as_posix():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "router" for target in node.targets
            ):
                if isinstance(node.value, ast.Call):
                    for keyword in node.value.keywords:
                        if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                            prefix = str(keyword.value.value)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not decorator.args:
                    continue
                function = decorator.func
                if not (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "router"
                ):
                    continue
                if isinstance(decorator.args[0], ast.Constant):
                    discovered.add(prefix + str(decorator.args[0].value))
    return discovered


def matches_router_path(documented: str, routed: str) -> bool:
    documented = documented.rstrip("/") or "/"
    routed = routed.rstrip("/") or "/"
    pattern = re.escape(routed)
    pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", pattern)
    return re.fullmatch(pattern, documented) is not None


def is_autoscale_api_document(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return rel.startswith("autoscale-source-split/03-shared-api-dashboard/") or rel.endswith(
        "01-monitoring-layer/docs/LLM_WORKLOAD_MONITORING_IMPLEMENTATION_LOG.md"
    )


def main() -> int:
    paths = tracked_files()
    documents = sorted({path for path in paths if path.suffix.lower() in DOC_SUFFIXES} | set((ROOT / "docs").rglob("*.md")))
    api_paths = router_paths(paths)
    findings: list[Finding] = []
    external_urls: set[str] = set()

    for document in documents:
        text = document.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for target in MARKDOWN_LINK.findall(line):
                if target.startswith(("http://", "https://")):
                    external_urls.add(target)
                    continue
                local, anchor = local_target(document, target)
                if local is None:
                    continue
                if not local.exists():
                    findings.append(Finding("ERROR", document, number, f"missing Markdown target: {target}"))
                    continue
                if anchor and local.suffix.lower() == ".md" and github_anchor(anchor) not in document_anchors(local):
                    findings.append(Finding("ERROR", document, number, f"missing Markdown anchor: {target}"))

            for command_path in INLINE_PATH.findall(line):
                if not (ROOT / command_path).is_file():
                    findings.append(Finding("ERROR", document, number, f"missing command entrypoint: {command_path}"))

            for endpoint in API_PATH.findall(line) if is_autoscale_api_document(document) else ():
                if endpoint.startswith("/api/") and not any(matches_router_path(endpoint, route) for route in api_paths):
                    findings.append(Finding("ERROR", document, number, f"documented API path is not routed: {endpoint}"))

    for finding in findings:
        print(f"{finding.level}: {finding.document.relative_to(ROOT)}:{finding.line}: {finding.message}")
    print(f"Scanned {len(documents)} documents; discovered {len(api_paths)} API paths.")
    print(f"External URLs found (not requested): {len(external_urls)}")
    for url in sorted(external_urls):
        print(f"EXTERNAL: {url}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
