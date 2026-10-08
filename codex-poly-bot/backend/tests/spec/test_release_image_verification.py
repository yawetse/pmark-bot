"""A green waiter after rollback must not certify the wrong release image."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location(
    "release_image_verifier", Path(__file__).resolve().parents[3] / "scripts/verify-release-images.py",
)
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
SHA = "f" * 40


def metadata_reader(*, scenario=None, count=1):
    def read(*args):
        operation = args[:2]
        if operation == ("ecs", "describe-services"):
            name = args[args.index("--services") + 1]
            if scenario == "missing_service":
                return []
            deployments = [{"status": "PRIMARY", "state": "COMPLETED"}]
            if scenario == "old_active_deployment":
                deployments.append({"status": "ACTIVE", "state": "COMPLETED"})
            return [{"name": name, "desired": count, "running": count,
                     "pending": 1 if scenario == "pending" else 0,
                     "deployments": deployments}]
        if operation == ("ecr", "describe-images"):
            assert f"imageTag={SHA}" in args
            return None if scenario == "missing_image" else "sha256:" + "a" * 64
        if operation == ("ecs", "list-tasks"):
            name = args[args.index("--service-name") + 1]
            return [] if scenario == "missing_task" else [name + f"/{i}" for i in range(count)]
        if operation == ("ecs", "describe-tasks"):
            ids = args[args.index("--tasks") + 1:args.index("--query")]
            tasks = []
            for i, task in enumerate(ids):
                component = "backend" if "backend" in task else "frontend"
                digest = "sha256:" + ("b" if scenario == "rollback" and i == count - 1 else "a") * 64
                tasks.append({"status": "RUNNING", "containers": [{
                    "name": "unrelated" if scenario == "wrong_container" else component,
                    "status": "RUNNING", "digest": digest}]})
            return tasks
        pytest.fail(f"Unexpected metadata lookup: {operation}")
    return read


@pytest.mark.parametrize("count", (1, 2))
def test_all_stable_tasks_must_match_requested_image(count):
    report = verifier.verify_release_images("production", SHA, metadata_reader(count=count))
    assert report["revision"] == SHA
    assert [image["tasks"] for image in report["images"]] == [count, count]


@pytest.mark.parametrize("scenario", (
    "rollback", "pending", "old_active_deployment", "missing_image",
    "missing_service", "missing_task", "wrong_container",
))
def test_rollback_or_incomplete_metadata_fails_closed(scenario):
    with pytest.raises(verifier.ReleaseVerificationError):
        verifier.verify_release_images("production", SHA, metadata_reader(scenario=scenario))


def test_one_wrong_replica_cannot_hide_among_correct_tasks():
    with pytest.raises(verifier.ReleaseVerificationError, match="running image differs"):
        verifier.verify_release_images("development", SHA, metadata_reader(scenario="rollback", count=2))


def test_cli_failure_does_not_expose_stderr(monkeypatch):
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(returncode=1, stdout="", stderr="private credential details"))
    with pytest.raises(verifier.ReleaseVerificationError, match="metadata lookup failed") as raised:
        verifier.aws_json("ecs", "describe-services")
    assert "private" not in str(raised.value)


def test_invalid_revision_cannot_lookup_mutable_latest_tag():
    def refuse(*args):
        pytest.fail("Invalid revision must not call AWS")
    with pytest.raises(verifier.ReleaseVerificationError):
        verifier.verify_release_images("production", "latest", refuse)


def test_cli_success_does_not_disclose_operational_digests(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["verify-release-images.py", "production", SHA])
    monkeypatch.setattr(verifier, "verify_release_images", lambda *args: {
        "images": [{"digest": "private operational metadata"}],
    })
    verifier.main()
    assert capsys.readouterr().out == "Requested release images verified\n"


def test_both_workflows_gate_images_before_other_guardrails():
    project = Path(__file__).resolve().parents[3]
    root = project.parent / ".github/workflows/codex-poly-bot-ci.yml"
    workflows = (root.read_text(), (project / ".github/workflows/ci.yml").read_text())
    assert workflows[0] == workflows[1]
    for stage in ("development", "production"):
        job = workflows[0].split(f"  deploy-{stage}:", 1)[1]
        if stage == "development":
            job = job.split("  deploy-production:", 1)[0]
        assert job.index("aws ecs wait services-stable") < job.index("Verify requested release images")
        assert job.index("Verify requested release images") < job.index("Verify funding release guardrails")
        assert f'verify-release-images.py {stage} "$GITHUB_SHA"' in job
