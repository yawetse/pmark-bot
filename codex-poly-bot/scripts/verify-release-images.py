"""Fail a release if stable ECS tasks do not run the requested immutable images."""

import argparse
import json
import re
import subprocess
import time


class ReleaseVerificationError(RuntimeError):
    pass


class ReleaseServiceNotReady(ReleaseVerificationError):
    """A recognized deployment transition may settle after the CLI waiter."""


def aws_json(*args):
    result = subprocess.run(
        ["aws", *args, "--region", "us-east-1", "--output", "json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        # Do not echo CLI stderr or credential/session details into CI logs.
        raise ReleaseVerificationError("AWS release metadata lookup failed")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise ReleaseVerificationError("AWS release metadata response is invalid") from exc


def verify_release_images(environment, revision, reader=aws_json):
    if environment not in ("development", "production") or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ReleaseVerificationError("Expected a release environment and full commit SHA")
    cluster = f"codex-poly-bot-{environment}-cluster"
    report = {"environment": environment, "revision": revision, "images": []}
    for component in ("backend", "frontend"):
        name = f"codex-poly-bot-{environment}-{component}"
        services = reader(
            "ecs", "describe-services", "--cluster", cluster, "--services", name,
            "--query", "services[].{name:serviceName,desired:desiredCount,running:runningCount,"
            "pending:pendingCount,deployments:deployments[].{status:status,state:rolloutState}}",
        )
        if len(services) != 1:
            raise ReleaseVerificationError(f"{component}: service metadata is missing")
        service = services[0]
        desired = service.get("desired", 0)
        if (service.get("name") != name or not isinstance(desired, int) or desired <= 0
                or any(not isinstance(service.get(k), int) or service[k] < 0
                       for k in ("running", "pending"))):
            raise ReleaseVerificationError(f"{component}: service metadata is invalid")
        if (service.get("running") != desired or service.get("pending") != 0
                or service.get("deployments") != [{"status": "PRIMARY", "state": "COMPLETED"}]):
            deployments = service.get("deployments", [])
            if (isinstance(deployments, list) and deployments
                    and any(d.get("status") == "PRIMARY" for d in deployments)
                    and all(d.get("status") in ("PRIMARY", "ACTIVE")
                            and d.get("state") in ("IN_PROGRESS", "COMPLETED") for d in deployments)):
                raise ReleaseServiceNotReady(f"{component}: service is not stable")
            raise ReleaseVerificationError(f"{component}: service is not stable")
        expected = reader(
            "ecr", "describe-images", "--repository-name", name,
            "--image-ids", f"imageTag={revision}",
            "--query", "imageDetails[0].imageDigest",
        )
        if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
            raise ReleaseVerificationError(f"{component}: requested immutable image is missing")
        task_ids = reader(
            "ecs", "list-tasks", "--cluster", cluster, "--service-name", name,
            "--desired-status", "RUNNING", "--query", "taskArns",
        )
        if len(task_ids) != desired:
            raise ReleaseVerificationError(f"{component}: running task count differs")
        tasks = reader(
            "ecs", "describe-tasks", "--cluster", cluster, "--tasks", *task_ids,
            "--query", "tasks[].{status:lastStatus,containers:containers[]."
            "{name:name,status:lastStatus,digest:imageDigest}}",
        )
        if len(tasks) != desired:
            raise ReleaseVerificationError(f"{component}: running task metadata is missing")
        for task in tasks:
            containers = [c for c in task.get("containers", []) if c.get("name") == component]
            if (task.get("status") != "RUNNING" or len(containers) != 1
                    or containers[0].get("status") != "RUNNING"
                    or containers[0].get("digest") != expected):
                raise ReleaseVerificationError(f"{component}: running image differs from requested release")
        report["images"].append({"component": component, "digest": expected, "tasks": desired})
    return report


def wait_for_release_images(environment, revision, reader=aws_json, *, timeout_seconds=90,
                            poll_seconds=5, clock=time.monotonic, sleeper=time.sleep):
    """Wait only for recognized rollout transitions; image failures stay terminal."""
    deadline = clock() + timeout_seconds
    while True:
        try:
            return verify_release_images(environment, revision, reader)
        except ReleaseServiceNotReady:
            remaining = deadline - clock()
            if remaining <= 0:
                raise
            sleeper(min(poll_seconds, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=("development", "production"))
    parser.add_argument("revision")
    args = parser.parse_args()
    try:
        wait_for_release_images(args.environment, args.revision)
    except (ReleaseVerificationError, KeyError, TypeError, OSError) as exc:
        # Malformed metadata fails closed; never print raw response data.
        parser.exit(1, f"Release image verification failed: {type(exc).__name__}\n")
    # CI may be public: attest success without disclosing operational digests.
    print("Requested release images verified")


if __name__ == "__main__":
    main()
