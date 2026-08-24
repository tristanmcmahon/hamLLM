# hamLLM

hamLLM is a small local command-line interface for models served by Ollama.
It does not read or send email, run a mail poller, or require Gmail credentials.

If the retired pre-0.1 mail bridge is still loaded on an existing machine, stop
it immediately with:

```bash
systemctl --user mask --now hamllm-bridge-timer.timer hamllm-bridge.service
```

The mask is local and reversible; it prevents the old Nix-store executable from
continuing to run even before the machine configuration is rebuilt.

## Install

```bash
python3 -m pip install .
```

## Use

```bash
hamllm doctor
hamllm models
hamllm run "Explain this shell error"
hamllm chat
```

The default model is `gpt-oss:20b`. Choose any installed Ollama tag with
`--model`, including a DeepSeek model:

```bash
hamllm run --model deepseek-r1:14b "Review this plan"
HAMLLM_MODEL=qwen3.6:27b hamllm chat
```

Configuration is deliberately small:

- `HAMLLM_HOST` — Ollama base URL (default `http://127.0.0.1:11434`)
- `HAMLLM_MODEL` — default installed model tag
- `HAMLLM_TIMEOUT` — request timeout in seconds

`run` also accepts a prompt on standard input and supports `--json`. `models`
and `doctor` support `--json` for scripts. Interactive chat understands
`/clear`, `/model NAME`, and `/exit`.

## Development

```bash
python3 -m compileall -q src tests
python3 -m pip install .
python3 -m unittest discover -s tests -v
hamllm --help
```

This repository currently uses `master` as its default branch.
