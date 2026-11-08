# granite-embedding-small-english-r2, int8 — the model `lspec find` runs

`lspec find` ranks a collection's supporting specs against a question by
meaning, with this embedding model. It runs on numpy alone, through code in
`lspec.py`; nothing here is executed on its own.

## Source

- **Model:** granite-embedding-small-english-r2, developed by the Granite
  Embedding Team, IBM: 47M parameters, ModernBERT architecture, 384-dimensional
  embeddings, [CLS] pooling. Paper: [Granite Embedding R2 Models](https://arxiv.org/abs/2508.21085).
- **Taken from:** <https://huggingface.co/ibm-granite/granite-embedding-small-english-r2>
  at revision `2ab6fa8ea2d674564defd37171ae19079b864b33` — `model.safetensors`
  (sha256 `dcbfaf2ee50d358763cbc0c08e5b045ecbf6aeb02dc0e86ffb910029bf9ebb5f`)
  and `tokenizer.json` (sha256 `6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30`).
- **IBM's code and documentation:** <https://github.com/ibm-granite/granite-embedding-models>

## License

Apache License 2.0, in `LICENSE` beside this file. This folder is distributed
under that license, not under live-spec's MIT license; it travels with every
copy of `lspec.py`, which pins the checksum of `LICENSE` with the model's files.

## Changes from the source

- `weights.npz` is IBM's `model.safetensors` (bfloat16) converted by
  `convert.py`: each matrix transposed to (input, output); the fused attention
  projection split into query, key and value, and the fused MLP projection into
  its GELU input and the gate it multiplies; every matrix quantized to int8 with
  one float32 scale per output column (per row for the embedding table). Norm
  weights are unchanged, as float32.
- The tokenizer is IBM's `tokenizer.json` repacked by `convert.py` into the
  same `weights.npz`, under names beginning `tok:`: the vocabulary in id order,
  each merge as the ids of its two parts in rank order, and the added tokens
  with their id and strip and normalization flags. The vocabulary, merges and
  added tokens are unchanged; the NFC normalizer, GPT-2 byte-level
  pre-tokenizer and `[CLS] … [SEP]` template it declares are implemented in
  `lspec.py`, and `convert.py` refuses a file that declares others.

## Rebuild

Download `model.safetensors` and `tokenizer.json` at the revision above, then, with numpy:

    python3 convert.py model.safetensors tokenizer.json weights.npz

The output is byte-identical to the `weights.npz` committed here.

## How it was checked

When this folder was built: the tokenizer in `lspec.py`
matched Hugging Face `tokenizers` on 3,418 strings (spec text, Unicode edge
cases, special tokens, random fuzz); the int8 embeddings matched IBM's model
run in `onnxruntime` at float32 to cosine similarity 0.99976 or better on 94
texts of 3 to 250 tokens; and int8 ranked a 22-question benchmark identically
to float32. `tests/test_lspec.py` keeps a reference embedding from that run.
