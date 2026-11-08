"""Build weights.npz from IBM's granite-embedding-small-english-r2 release.

    python3 convert.py MODEL.SAFETENSORS TOKENIZER.JSON weights.npz

Input: model.safetensors and tokenizer.json from
huggingface.co/ibm-granite/granite-embedding-small-english-r2 at the revision
README.md names (bfloat16, Hugging Face ModernBERT layout; byte-level BPE).
Output: the int8 weights lspec find runs, one scale per output column (per row
for the embedding table); 1-D norm weights stay float32; and the tokenizer's
vocabulary, merges and added tokens as arrays under "tok:". Needs numpy only.
"""
import io
import json
import struct
import sys
import zipfile

import numpy as np

LAYERS = 12


def read_safetensors(path):
    """name -> float32 array; reads the header and bf16 payload directly."""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        header = json.loads(f.read(n))
        data = f.read()
    header.pop("__metadata__", None)
    out = {}
    for name, info in header.items():
        if info["dtype"] != "BF16":
            raise SystemExit(f"{name}: expected BF16, found {info['dtype']}")
        start, end = info["data_offsets"]
        raw = np.frombuffer(data[start:end], dtype="<u2").astype(np.uint32) << 16
        out[name] = raw.view(np.float32).reshape(info["shape"])
    return out


def to_lspec_layout(st):
    """Hugging Face (out, in) matrices -> (in, out), fused projections split:
    Wqkv rows are q, k, v; Wi rows are the GELU input, then the gate it multiplies."""
    w = {"embed": st["embeddings.tok_embeddings.weight"],
         "embed_norm": st["embeddings.norm.weight"],
         "final_norm": st["final_norm.weight"]}
    for l in range(LAYERS):
        p = f"layers.{l}."
        q, k, v = np.split(st[p + "attn.Wqkv.weight"], 3)
        w[f"{l}.q"], w[f"{l}.k"], w[f"{l}.v"] = q.T, k.T, v.T
        w[f"{l}.o"] = st[p + "attn.Wo.weight"].T
        act, gate = np.split(st[p + "mlp.Wi.weight"], 2)
        w[f"{l}.gate"], w[f"{l}.up"] = act.T, gate.T
        w[f"{l}.down"] = st[p + "mlp.Wo.weight"].T
        w[f"{l}.mlp_norm"] = st[p + "mlp_norm.weight"]
        if l:
            w[f"{l}.attn_norm"] = st[p + "attn_norm.weight"]
    return {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in w.items()}


def quantize(weights):
    out = {}
    for name, a in weights.items():
        if a.ndim < 2:
            out[name] = a; continue
        axis = 1 if name == "embed" else 0
        scale = np.abs(a).max(axis=axis, keepdims=True) / 127.0
        scale[scale == 0] = 1.0
        out["q8:" + name] = np.round(a / scale).astype(np.int8)
        out["scale:" + name] = scale.astype(np.float32)
    return out


def strings(items):
    """UTF-8 strings as one byte blob and the end offset of each."""
    blobs = [x.encode("utf-8") for x in items]
    ends = np.cumsum([len(b) for b in blobs], dtype=np.int64).astype(np.int32)
    return np.frombuffer(b"".join(blobs), dtype=np.uint8), ends


def pack_tokenizer(path):
    """tokenizer.json -> arrays: tokens in id order, each merge as the ids of its
    two parts in rank order, added tokens with (id, lstrip, rstrip, normalized).
    The normalizer (NFC), pre-tokenizer (GPT-2 byte level) and [CLS] ... [SEP]
    template are fixed in lspec.py; this refuses a file that says otherwise."""
    with open(path, encoding="utf-8") as f:
        spec = json.load(f)
    model = spec["model"]
    if (model["type"], spec["normalizer"], spec["pre_tokenizer"]["type"]) != ("BPE", {"type": "NFC"}, "ByteLevel"):
        raise SystemExit("tokenizer.json: not the NFC byte-level BPE lspec.py implements")
    vocab = model["vocab"]
    tokens = sorted(vocab, key=vocab.get)
    if [vocab[t] for t in tokens] != list(range(len(tokens))):
        raise SystemExit("tokenizer.json: vocabulary ids are not 0..n-1")
    pairs = [m if isinstance(m, list) else m.split(" ") for m in model["merges"]]
    added = spec["added_tokens"]
    out = {"tok:merges": np.array([[vocab[a], vocab[b]] for a, b in pairs], dtype=np.int32),
           "tok:added_meta": np.array([[a["id"], a["lstrip"], a["rstrip"], a["normalized"]] for a in added],
                                      dtype=np.int32)}
    out["tok:vocab"], out["tok:vocab_ends"] = strings(tokens)
    out["tok:added"], out["tok:added_ends"] = strings(a["content"] for a in added)
    return out


def save(path, arrays):
    """An .npz numpy reads, written byte-reproducibly: sorted names, fixed
    timestamps, no compression, so a rebuild matches the pinned checksum."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for name in sorted(arrays):
            buf = io.BytesIO()
            np.lib.format.write_array(buf, arrays[name], allow_pickle=False)
            info = zipfile.ZipInfo(name + ".npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            z.writestr(info, buf.getvalue())


if __name__ == "__main__":
    src, tokenizer, dest = sys.argv[1:4]
    save(dest, {**quantize(to_lspec_layout(read_safetensors(src))), **pack_tokenizer(tokenizer)})
