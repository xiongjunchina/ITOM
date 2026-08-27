#!/usr/bin/env python3
"""Local lifecycle ledger and gates for ITOM coding tasks."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Ledger:
    def __init__(self, root: Path):
        self.directory = root / ".itom-task"
        self.current = self.directory / "current.json"
        self.history = self.directory / "history.jsonl"

    def load(self) -> dict:
        if not self.current.exists():
            raise SystemExit("No active ITOM task. Run 'start' before implementation.")
        return json.loads(self.current.read_text(encoding="utf-8"))

    def save(self, data: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.current.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.current)


def event(data: dict, kind: str, **details: object) -> None:
    data["events"].append({"at": now(), "type": kind, **details})


def require(data: dict, condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def start(args: argparse.Namespace, ledger: Ledger) -> None:
    if ledger.current.exists():
        raise SystemExit("An ITOM task is already active; close it before starting another.")
    timestamp = now()
    data = {
        "schema": 2, "id": args.id, "track": args.track,
        "grade": args.grade, "scope": args.scope,
        "acceptance": args.acceptance, "started_at": timestamp, "status": "diagnosing",
        "same_target_failures": {}, "root_cause_required": False,
        "target_verified_at": None, "docs_assessed_at": None,
        "candidate_frozen_at": None, "candidate_number": 0,
        "local_candidate_ready_at": None, "idc_release_approved_at": None,
        "ci_attempts": 0, "idc_attempts": 0, "external_blocker_seconds": 0,
        "events": [{"at": timestamp, "type": "started"}],
    }
    ledger.save(data)
    print(f"Started {args.id}: track={args.track}, grade={args.grade}, scope={args.scope}")


def mutate(args: argparse.Namespace, ledger: Ledger) -> None:
    data = ledger.load()
    cmd = args.command
    if cmd == "regrade":
        event(data, cmd, previous=data["grade"], grade=args.grade, reason=args.reason)
        data["grade"] = args.grade
    elif cmd == "fail":
        failures = data["same_target_failures"].get(args.target, 0) + 1
        data["same_target_failures"][args.target] = failures
        event(data, cmd, target=args.target, count=failures, reason=args.reason)
        if failures >= 2:
            data["root_cause_required"] = True
            data["status"] = "root_cause_required"
            print("Second failure reached: stop patching and record root cause.")
    elif cmd == "root-cause":
        require(data, data["root_cause_required"], "Root-cause review is not currently required.")
        event(data, cmd, summary=args.summary)
        data.update(root_cause_required=False, status="diagnosing", target_verified_at=None,
                    docs_assessed_at=None, candidate_frozen_at=None,
                    local_candidate_ready_at=None, idc_release_approved_at=None,
                    ci_attempts=0, idc_attempts=0)
        for key in ("ci_started_at", "ci_finished_at", "ci_result",
                    "idc_started_at", "idc_finished_at", "idc_result"):
            data.pop(key, None)
    elif cmd == "target-verified":
        require(data, not data["root_cause_required"], "Root-cause review is required before verification.")
        data["target_verified_at"] = now(); data["status"] = "target_verified"
        event(data, cmd, evidence=args.evidence)
    elif cmd == "docs-assessed":
        require(data, bool(data["target_verified_at"]), "Verify the changed real target before formal documentation.")
        data["docs_assessed_at"] = now(); data["status"] = "docs_assessed"
        event(data, cmd, assessment=args.assessment)
    elif cmd == "freeze":
        require(data, bool(data["target_verified_at"]), "Focused target acceptance has not passed.")
        require(data, bool(data["docs_assessed_at"]), "Documentation has not been assessed after acceptance.")
        require(data, not data["root_cause_required"], "Root-cause review is required.")
        data["candidate_number"] += 1; data["candidate_frozen_at"] = now(); data["status"] = "candidate_frozen"
        event(data, cmd, candidate=data["candidate_number"])
    elif cmd == "ci-start":
        require(data, bool(data["candidate_frozen_at"]), "Freeze a candidate before full CI.")
        require(data, data["ci_attempts"] == 0, "Full CI already ran for this candidate; diagnose and freeze a new candidate.")
        data["ci_attempts"] += 1; data["ci_started_at"] = now(); data["status"] = "ci_running"
        event(data, cmd, reference=args.reference)
    elif cmd == "ci-finish":
        require(data, data.get("status") == "ci_running", "CI is not recorded as running.")
        data["ci_finished_at"] = now(); data["ci_result"] = args.result
        data["status"] = "ci_passed" if args.result == "passed" else "ci_failed"
        event(data, cmd, result=args.result)
    elif cmd == "local-candidate-ready":
        require(data, data.get("track") == "feature-local",
                "Only feature-local tasks can become local candidates.")
        require(data, data.get("ci_result") == "passed",
                "Passing CI is required before a local candidate is ready.")
        data["local_candidate_ready_at"] = now(); data["status"] = "local_candidate_ready"
        event(data, cmd, evidence=args.evidence)
    elif cmd == "approve-idc":
        require(data, data.get("track") in {"production-fix", "feature-local"},
                "Code-candidate tasks cannot be approved for IDC release.")
        require(data, data.get("ci_result") == "passed",
                "Passing CI is required before IDC release approval.")
        if data.get("track") == "feature-local":
            require(data, bool(data.get("local_candidate_ready_at")),
                    "Feature-local work must reach local-candidate-ready first.")
        data["idc_release_approved_at"] = now(); data["status"] = "idc_release_approved"
        event(data, cmd, approval=args.approval)
    elif cmd == "idc-start":
        require(data, data.get("ci_result") == "passed", "Passing CI is required before IDC release.")
        require(data, bool(data.get("idc_release_approved_at")),
                "Explicit IDC release approval is required before deployment.")
        require(data, data["idc_attempts"] == 0, "IDC release already ran for this candidate.")
        data["idc_attempts"] += 1; data["idc_started_at"] = now(); data["status"] = "idc_running"
        event(data, cmd, tag=args.tag)
    elif cmd == "idc-finish":
        require(data, data.get("status") == "idc_running", "IDC release is not recorded as running.")
        data["idc_finished_at"] = now(); data["idc_result"] = args.result
        data["status"] = "idc_accepted" if args.result == "passed" else "idc_failed"
        event(data, cmd, result=args.result)
    elif cmd == "blocker":
        require(data, args.seconds >= 0, "Blocker seconds cannot be negative.")
        data["external_blocker_seconds"] += args.seconds
        event(data, cmd, seconds=args.seconds, reason=args.reason)
    ledger.save(data)
    print(f"{cmd}: {data['status']}")


def gate(ledger: Ledger) -> None:
    data = ledger.load()
    require(data, bool(data["target_verified_at"]), "Commit blocked: focused target acceptance has not passed.")
    require(data, bool(data["docs_assessed_at"]), "Commit blocked: documentation assessment is missing.")
    require(data, not data["root_cause_required"], "Commit blocked: root-cause review is required.")
    print(f"Gate passed for {data['id']}")


def report(ledger: Ledger) -> None:
    data = ledger.load(); end = datetime.now(timezone.utc); total = int((end - parse_time(data["started_at"])).total_seconds())
    pipeline = 0
    for prefix in ("ci", "idc"):
        if data.get(f"{prefix}_started_at"):
            finish = parse_time(data[f"{prefix}_finished_at"]) if data.get(f"{prefix}_finished_at") else end
            pipeline += int((finish - parse_time(data[f"{prefix}_started_at"])).total_seconds())
    external = data["external_blocker_seconds"]
    output = {"id": data["id"], "status": data["status"], "track": data.get("track", "legacy"), "grade": data["grade"],
              "development_seconds": max(0, total - pipeline - external), "pipeline_seconds": pipeline,
              "external_blocker_seconds": external,
              "first_pass_acceptance": max(data["same_target_failures"].values(), default=0) == 0,
              "candidate_count": data["candidate_number"], "ci_attempts": data["ci_attempts"], "idc_attempts": data["idc_attempts"]}
    print(json.dumps(output, ensure_ascii=False, indent=2))


def close(args: argparse.Namespace, ledger: Ledger) -> None:
    data = ledger.load()
    allowed = data["status"] in {"ci_passed", "idc_accepted"}
    if args.outcome == "local-candidate":
        allowed = data["status"] == "local_candidate_ready"
    require(data, args.outcome == "blocked" or allowed,
            "Only a passed, local-candidate-ready, or explicitly blocked task can be closed.")
    data.update(closed_at=now(), outcome=args.outcome)
    with ledger.history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    ledger.current.unlink(); print(f"Closed {data['id']}: {args.outcome}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(); sub = result.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start"); p.add_argument("--id", required=True); p.add_argument("--track", choices=("production-fix", "feature-local", "code-candidate"), required=True); p.add_argument("--grade", choices="SML", required=True); p.add_argument("--scope", required=True); p.add_argument("--acceptance", required=True)
    p = sub.add_parser("regrade"); p.add_argument("--grade", choices="SML", required=True); p.add_argument("--reason", required=True)
    p = sub.add_parser("fail"); p.add_argument("--target", required=True); p.add_argument("--reason", required=True)
    p = sub.add_parser("root-cause"); p.add_argument("--summary", required=True)
    p = sub.add_parser("target-verified"); p.add_argument("--evidence", required=True)
    p = sub.add_parser("docs-assessed"); p.add_argument("--assessment", required=True)
    sub.add_parser("freeze")
    p = sub.add_parser("ci-start"); p.add_argument("--reference", required=True)
    p = sub.add_parser("ci-finish"); p.add_argument("--result", choices=("passed", "failed"), required=True)
    p = sub.add_parser("local-candidate-ready"); p.add_argument("--evidence", required=True)
    p = sub.add_parser("approve-idc"); p.add_argument("--approval", required=True)
    p = sub.add_parser("idc-start"); p.add_argument("--tag", required=True)
    p = sub.add_parser("idc-finish"); p.add_argument("--result", choices=("passed", "failed"), required=True)
    p = sub.add_parser("blocker"); p.add_argument("--seconds", type=int, required=True); p.add_argument("--reason", required=True)
    sub.add_parser("gate"); sub.add_parser("report")
    p = sub.add_parser("close"); p.add_argument("--outcome", choices=("complete", "local-candidate", "blocked"), required=True)
    return result


def main() -> None:
    args = parser().parse_args(); root = Path(os.environ.get("ITOM_REPO_ROOT", Path(__file__).resolve().parents[1])); ledger = Ledger(root)
    if args.command == "start": start(args, ledger)
    elif args.command == "gate": gate(ledger)
    elif args.command == "report": report(ledger)
    elif args.command == "close": close(args, ledger)
    else: mutate(args, ledger)


if __name__ == "__main__":
    main()
