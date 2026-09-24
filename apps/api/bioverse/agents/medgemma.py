"""MedGemma on a Vertex AI endpoint: Google's open medical model, deployed from Model Garden.

Configure with the endpoint that `deploy/gcp/medgemma.sh` creates:

    BIOVERSE_MEDGEMMA_ENDPOINT   endpoint ID (numbers) or full resource name
    BIOVERSE_MEDGEMMA_DNS        dedicated endpoint hostname, when the endpoint has one (Model Garden default)
    BIOVERSE_MEDGEMMA_REGION     default us-central1
    BIOVERSE_MEDGEMMA_MODEL      label recorded in audit, e.g. medgemma-1.5-4b-it
    BIOVERSE_MEDGEMMA_MULTIMODAL "true" for image-capable variants (4B, 27B multimodal)
    GOOGLE_CLOUD_PROJECT / BIOVERSE_GCP_PROJECT

Requests use the endpoint's chat-completions format. MedGemma has no schema-constrained decoding here, so
the schema goes in the system prompt, the reply is parsed and validated with Pydantic, and one repair turn
is allowed. Anything else raises MedGemmaUnavailable and the caller moves on (another provider, or rules).

Auth: on Cloud Run the runtime service account's token comes from the metadata server (the account needs
Vertex AI User). Locally, `gcloud auth print-access-token` is used, or BIOVERSE_GCP_ACCESS_TOKEN.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

METADATA_TOKEN_URL = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
_THOUGHT = re.compile(r"<unused94>.*?<unused95>", re.S)
_token: tuple[str, float] | None = None


class MedGemmaUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(os.getenv("BIOVERSE_MEDGEMMA_ENDPOINT") or os.getenv("BIOVERSE_MEDGEMMA_URL"))


def model_label() -> str:
    return os.getenv("BIOVERSE_MEDGEMMA_MODEL", "medgemma")


def multimodal() -> bool:
    return os.getenv("BIOVERSE_MEDGEMMA_MULTIMODAL", "true").lower() in ("1", "true", "yes")


def predict_url() -> str:
    if url := os.getenv("BIOVERSE_MEDGEMMA_URL"):
        return url
    endpoint = os.environ["BIOVERSE_MEDGEMMA_ENDPOINT"]
    region = os.getenv("BIOVERSE_MEDGEMMA_REGION", "us-central1")
    if not endpoint.startswith("projects/"):
        project = os.getenv("BIOVERSE_GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise MedGemmaUnavailable("GOOGLE_CLOUD_PROJECT is not set")
        endpoint = f"projects/{project}/locations/{region}/endpoints/{endpoint}"
    host = os.getenv("BIOVERSE_MEDGEMMA_DNS") or f"{region}-aiplatform.googleapis.com"
    return f"https://{host}/v1/{endpoint}:predict"


def _access_token() -> str:
    global _token
    if token := os.getenv("BIOVERSE_GCP_ACCESS_TOKEN"):
        return token
    if _token and _token[1] > time.time() + 60:
        return _token[0]
    try:
        req = urllib.request.Request(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        _token = (data["access_token"], time.time() + int(data.get("expires_in", 300)))
        return _token[0]
    except (OSError, ValueError, KeyError):
        pass
    try:
        out = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            _token = (out.stdout.strip(), time.time() + 1800)
            return _token[0]
    except (OSError, subprocess.SubprocessError):
        pass
    raise MedGemmaUnavailable("no Google Cloud credentials")


def to_chat_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style messages (text and base64 image blocks) to chat-completions messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": [{"type": "text", "text": system}]}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            parts = [{"type": "text", "text": content}]
        else:
            parts = []
            for block in content:
                kind = block.get("type")
                if kind == "text":
                    parts.append({"type": "text", "text": block["text"]})
                elif kind == "image":
                    if not multimodal():
                        raise MedGemmaUnavailable("this MedGemma endpoint is text-only")
                    src = block["source"]
                    parts.append({"type": "image_url",
                                  "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
                elif kind == "document":
                    raise MedGemmaUnavailable("documents are not supported by MedGemma here")
        out.append({"role": "assistant" if m["role"] == "assistant" else "user", "content": parts})
    return out


def extract_json(text: str) -> str:
    text = _THOUGHT.sub("", text).replace("<unused94>", "").replace("<unused95>", "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return text[start:end + 1]


def schema_instructions(output_format: type[BaseModel]) -> str:
    schema = json.dumps(output_format.model_json_schema(), separators=(",", ":"))
    return ("\n\nReply with ONLY one JSON object that validates against this JSON Schema. No prose, no code "
            f"fences, no comments.\nJSON Schema: {schema}")


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        log.error("MedGemma endpoint error %s: %s", exc.code, detail)
        raise MedGemmaUnavailable(f"endpoint error {exc.code}") from exc
    except (OSError, ValueError) as exc:
        log.error("MedGemma endpoint unreachable: %s", exc)
        raise MedGemmaUnavailable("endpoint unreachable") from exc


def _content(response: dict[str, Any]) -> str:
    pred = response.get("predictions")
    if isinstance(pred, list):
        pred = pred[0] if pred else {}
    try:
        return pred["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise MedGemmaUnavailable("unexpected response shape") from exc


def parse(*, system: str, messages: list[dict[str, Any]], output_format: type[T], max_tokens: int = 4000,
          timeout: float = 90.0) -> T:
    chat = to_chat_messages(system + schema_instructions(output_format), messages)
    url = predict_url()
    for attempt in range(2):
        body = {"instances": [{"@requestFormat": "chatCompletions", "messages": chat,
                               "max_tokens": max_tokens, "temperature": 0}]}
        text = _content(_post(url, body, timeout))
        try:
            return output_format.model_validate_json(extract_json(text))
        except (ValueError, ValidationError) as exc:
            if attempt == 1:
                log.warning("MedGemma output did not match the schema: %s", str(exc)[:200])
                raise MedGemmaUnavailable("output did not match schema") from exc
            chat = chat + [
                {"role": "assistant", "content": [{"type": "text", "text": text[:4000]}]},
                {"role": "user", "content": [{"type": "text", "text":
                    f"That reply was not valid for the schema ({str(exc)[:300]}). Reply with only the corrected JSON object."}]},
            ]
    raise MedGemmaUnavailable("unreachable")
