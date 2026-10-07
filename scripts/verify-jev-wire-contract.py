#!/usr/bin/env python3
"""Verify the Jev shadow lane's WIRE BODY against the vendor's own OpenAPI schema.

Why this exists: the lane's first cut sent `questions` as an array of {key, kind, question}
objects. OpenRouter's Decisions API takes an OBJECT keyed by question name whose members are
{type: "noul"|"choice"|"score", instructions, criteria?} — so that payload would have 400'd on
every call while the instrument looked healthy (it stores the error on the row). The lane is
default-off and there is no key yet, which is exactly when a shape bug can hide: nothing fails
loudly. This script closes that hole without a key by validating the real request body our code
builds against the published schema.

What it does (all read-only; writes nothing into the repo):
  1. Downloads https://openrouter.ai/docs/openapi/openapi.yaml (or uses --spec PATH).
  2. Runs `npx tsx scripts/mark-shadow-jev.ts --dry-run` and reads the request body it prints.
  3. Validates that body against the /api/alpha/decisions request schema
     (components.schemas.DecisionsRequest, $refs resolved).
  4. CONTROL: validates the vendor's OWN example from the same spec. If the control fails the
     validator is broken, not the payload — the script says so instead of blaming the code.

Deps: pyyaml + jsonschema (`pip install pyyaml jsonschema`, or any venv). Exits 2 with that
instruction rather than silently passing when they are missing.

Usage:  python3 scripts/verify-jev-wire-contract.py [--spec PATH] [--repo PATH]
Exit:   0 = our body is schema-valid, 1 = it is not, 2 = the check could not run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

SPEC_URL = "https://openrouter.ai/docs/openapi/openapi.yaml"
DECISIONS_PATH = "/api/alpha/decisions"


def resolve_refs(node, schemas, depth=0):
    """Inline every #/components/schemas $ref so jsonschema can validate a single document."""
    if depth > 60:
        return node
    if isinstance(node, dict):
        if "$ref" in node and node["$ref"].startswith("#/components/schemas/"):
            name = node["$ref"].rsplit("/", 1)[-1]
            merged = dict(resolve_refs(schemas[name], schemas, depth + 1))
            for k, v in node.items():
                if k != "$ref":
                    merged[k] = resolve_refs(v, schemas, depth + 1)
            return merged
        # discriminator/example/examples are OpenAPI bookkeeping, not JSON Schema
        return {
            k: resolve_refs(v, schemas, depth + 1)
            for k, v in node.items()
            if k not in ("discriminator", "example", "examples")
        }
    if isinstance(node, list):
        return [resolve_refs(v, schemas, depth + 1) for v in node]
    return node


def fetch_spec(spec_path: str | None) -> dict:
    import yaml

    if spec_path:
        raw = Path(spec_path).read_bytes()
    else:
        # The docs host 403s a bare urllib UA, so identify honestly and fall back to curl.
        req = urllib.request.Request(SPEC_URL, headers={"User-Agent": "copybot-wire-contract-check/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
        except Exception as e:  # noqa: BLE001 — any failure here means "use --spec"
            curl = subprocess.run(
                ["curl", "-sL", "--max-time", "60", SPEC_URL], capture_output=True
            )
            if curl.returncode != 0 or not curl.stdout:
                sys.exit(f"could not fetch {SPEC_URL} ({e}); pass --spec PATH")
            raw = curl.stdout
    return yaml.safe_load(raw)


def built_request_body(repo: Path) -> dict:
    """The body our lane would actually POST — printed by the lane's own --dry-run path."""
    out = subprocess.run(
        ["npx", "tsx", "scripts/mark-shadow-jev.ts", "--dry-run"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=300,
    )
    blob = out.stdout + out.stderr
    for line in blob.splitlines():
        if "--dry-run request: " in line:
            return json.loads(line.split("--dry-run request: ", 1)[1])
    sys.exit(f"could not read the request body from the lane's --dry-run output:\n{blob[-2000:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", help="local openapi.yaml (default: download from OpenRouter)")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()

    try:
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401
    except ImportError as e:
        print(f"SKIP: {e.name} is required — pip install pyyaml jsonschema", file=sys.stderr)
        return 2

    import jsonschema

    repo = Path(args.repo)
    spec = fetch_spec(args.spec)
    op = spec["paths"][DECISIONS_PATH]["post"]
    schemas = spec["components"]["schemas"]
    req_schema = resolve_refs(op["requestBody"]["content"]["application/json"]["schema"], schemas)
    documented_example = op["requestBody"]["content"]["application/json"].get("example")

    validator = jsonschema.Draft202012Validator(req_schema)
    failures = 0

    # CONTROL first: a broken validator must not be able to bless our payload.
    if documented_example is not None:
        errs = list(validator.iter_errors(documented_example))
        print(f"control (vendor's own example vs DecisionsRequest): {'VALID' if not errs else 'INVALID'}")
        if errs:
            print("  the validator or the spec it loaded is wrong — fix this before reading below:")
            for e in errs[:5]:
                print(f"   - {list(e.path)} {e.message[:160]}")
            return 2
    else:
        print("control: the spec carries no example — control skipped (validator unproven)")

    body = built_request_body(repo)
    errs = sorted(validator.iter_errors(body), key=lambda e: list(e.path))
    if errs:
        failures += 1
        print(f"OUR request body vs DecisionsRequest: INVALID ({len(errs)} error(s))")
        for e in errs[:10]:
            print(f"   - {list(e.path)} {e.message[:200]}")
    else:
        qs = body["questions"]
        kinds = {k: q["type"] for k, q in qs.items()}
        print(f"OUR request body vs DecisionsRequest: VALID")
        print(f"  model={body['model']} questions_keyed_by_name={list(qs)} kinds={kinds}")

    # The shape that got this lane into trouble, asserted absent rather than assumed absent.
    if isinstance(body["questions"], list):
        failures += 1
        print("FAIL: questions is a LIST — the documented shape is an object keyed by name")

    print("PASS" if failures == 0 else "FAIL")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
