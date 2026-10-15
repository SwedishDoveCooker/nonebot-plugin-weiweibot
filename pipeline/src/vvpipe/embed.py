"""Sentence vectors for the subtitle lines (BGE small zh, ONNX on CPU).

Every machine must use the very same model file, otherwise vectors built on the PC and vectors
built on the bot's box would not be comparable. Vectors are stored per episode as raw
little-endian float16, row-major, one unit-length row of DIM values per line of the episode's
index file:

    vectors/ep0352.f16
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

DIM = 512
MAX_TOKENS = 64


class Embedder:
    def __init__(self, model_dir: Path, threads: int | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=MAX_TOKENS)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(
            str(model_dir / "model.onnx"), opts, providers=["CPUExecutionProvider"]
        )
        self.wants_types = "token_type_ids" in {i.name for i in self.sess.get_inputs()}

    def encode(self, texts: list[str], batch: int = 64) -> np.ndarray:
        """Unit-length CLS embeddings, shape (len(texts), DIM), float32."""
        rows = []
        for i in range(0, len(texts), batch):
            enc = self.tok.encode_batch(texts[i : i + batch])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            feed = {
                "input_ids": ids,
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64),
            }
            if self.wants_types:
                feed["token_type_ids"] = np.zeros_like(ids)
            cls = self.sess.run(None, feed)[0][:, 0, :]
            rows.append(cls / np.linalg.norm(cls, axis=1, keepdims=True).clip(1e-9))
        return np.vstack(rows).astype(np.float32) if rows else np.zeros((0, DIM), np.float32)


class RemoteEmbedder:
    """Same interface as Embedder, but asks the local embed-serve process.

    The updater daemon uses it so only one copy of the model sits in memory.
    """

    def __init__(self, url: str = "http://127.0.0.1:8765", timeout: float = 120.0):
        self.url, self.timeout = url.rstrip("/"), timeout

    def encode(self, texts: list[str], batch: int = 32) -> np.ndarray:
        import urllib.request

        rows: list[list[float]] = []
        for i in range(0, len(texts), batch):
            body = json.dumps({"texts": texts[i : i + batch]}).encode()
            req = urllib.request.Request(
                f"{self.url}/embed", body, {"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                rows += json.loads(resp.read())["vecs"]
        return np.array(rows, dtype=np.float32).reshape(len(rows), DIM)


def vectors_path(index_dir: Path, ep: int) -> Path:
    return index_dir / "vectors" / f"ep{ep:04d}.f16"


def embed_episode(index_dir: Path, ep: int, embedder, force: bool = False) -> int:
    """Write the vectors of one indexed episode; returns the number of lines embedded."""
    idx = index_dir / "entries" / f"ep{ep:04d}.jsonl"
    out = vectors_path(index_dir, ep)
    raw = idx.read_bytes()
    # Cheap completeness check first: counting lines avoids parsing 350 files every few minutes.
    n_lines = sum(1 for line in raw.split(b"\n") if line.strip())
    if out.exists() and not force and out.stat().st_size == n_lines * DIM * 2:
        return 0
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    vecs = embedder.encode([r["text"] for r in rows])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".f16.tmp")
    with open(tmp, "wb") as f:
        f.write(vecs.astype("<f2").tobytes())
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out)
    return len(rows)


def embed_missing(index_dir: Path, embedder, log=print) -> int:
    total = 0
    for idx in sorted((index_dir / "entries").glob("ep*.jsonl")):
        ep = int(idx.stem[2:])
        n = embed_episode(index_dir, ep, embedder)
        if n:
            log(f"ep{ep}: {n} vectors")
            total += n
    return total


def serve(embedder, host: str = "127.0.0.1", port: int = 8765) -> None:
    """A tiny local HTTP service so the Go bot can embed search queries."""
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - http.server API
            self._reply(200, {"ok": True, "dim": DIM}) if self.path == "/health" else self._reply(
                404, {}
            )

        def do_POST(self):  # noqa: N802
            if self.path != "/embed":
                return self._reply(404, {})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                texts = json.loads(self.rfile.read(min(n, 1 << 20)))["texts"]
                if not isinstance(texts, list) or not 1 <= len(texts) <= 64:
                    raise ValueError("texts must be a list of 1..64 strings")
                texts = [str(t)[:200] for t in texts]
            except (ValueError, KeyError, TypeError) as err:
                return self._reply(400, {"error": str(err)})
            with lock:
                vecs = embedder.encode(texts)
            self._reply(200, {"vecs": np.round(vecs, 5).tolist()})

        def log_message(self, *args):  # keep the journal quiet
            return

    ThreadingHTTPServer((host, port), Handler).serve_forever()
