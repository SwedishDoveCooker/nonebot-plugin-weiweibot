import json

import numpy as np

from vvpipe import embed


class FakeEmbedder:
    """Stands in for the ONNX model: a deterministic unit vector per text."""

    def __init__(self):
        self.calls = 0

    def encode(self, texts):
        self.calls += 1
        out = np.zeros((len(texts), embed.DIM), np.float32)
        for i, t in enumerate(texts):
            out[i, hash(t) % embed.DIM] = 1.0
        return out


def _index(tmp_path, ep, texts):
    d = tmp_path / "entries"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"ep{ep:04d}.jsonl").write_text(
        "".join(json.dumps({"ep": ep, "text": t}, ensure_ascii=False) + "\n" for t in texts),
        "utf-8",
    )


def test_vectors_file_has_one_row_per_line_and_is_not_redone(tmp_path):
    _index(tmp_path, 7, ["你好", "再见", "谢谢"])
    fake = FakeEmbedder()
    assert embed.embed_episode(tmp_path, 7, fake) == 3
    f = embed.vectors_path(tmp_path, 7)
    assert f.stat().st_size == 3 * embed.DIM * 2  # float16
    assert embed.embed_episode(tmp_path, 7, fake) == 0  # already complete
    assert fake.calls == 1


def test_a_truncated_vectors_file_is_rebuilt(tmp_path):
    _index(tmp_path, 8, ["甲", "乙"])
    f = embed.vectors_path(tmp_path, 8)
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\x00" * 10)
    assert embed.embed_episode(tmp_path, 8, FakeEmbedder()) == 2
    assert f.stat().st_size == 2 * embed.DIM * 2


def test_remote_embedder_round_trips_through_the_http_service():
    import socket
    import threading
    import time

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    threading.Thread(
        target=embed.serve, args=(FakeEmbedder(),), kwargs={"port": port}, daemon=True
    ).start()
    remote = embed.RemoteEmbedder(f"http://127.0.0.1:{port}", timeout=5)
    for _ in range(50):  # wait for the server thread
        try:
            vecs = remote.encode(["你好", "再见", "谢谢"], batch=2)
            break
        except OSError:
            time.sleep(0.1)
    assert vecs.shape == (3, embed.DIM)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-4)


def test_embed_missing_covers_every_episode(tmp_path):
    _index(tmp_path, 1, ["a"])
    _index(tmp_path, 2, ["b", "c"])
    assert embed.embed_missing(tmp_path, FakeEmbedder(), log=lambda s: None) == 3
    assert embed.embed_missing(tmp_path, FakeEmbedder(), log=lambda s: None) == 0


def test_openai_response_shape():
    import numpy as np

    from vvpipe import embed

    body = embed.openai_response(np.array([[0.5, 0.25], [1.0, 0.0]], dtype=np.float32), "m")
    assert body["object"] == "list" and body["model"] == "m"
    assert [d["index"] for d in body["data"]] == [0, 1]
    assert body["data"][0]["embedding"] == [0.5, 0.25]
