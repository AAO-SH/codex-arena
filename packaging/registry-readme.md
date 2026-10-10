# Codex Arena

![Codex Arena](https://raw.githubusercontent.com/AAO-SH/codex-arena/main/assets/codex-arena-logo.png)

Put strategies to the test and turn the best methods into reusable playbooks for Codex. Compare strategies, models, and reasoning efforts on recurring tasks, with configuration and results stored in your project.

Requires Python 3.11+. The npm command also requires Node.js 22+. Installing the package does not start tournaments or install runtime dependencies automatically.

```bash
npx @aao-sh/codex-arena install --workspace . --bootstrap
uvx --from codex-arena codex-arena install --workspace . --bootstrap
```

Run from your project folder; `--workspace .` uses the current directory. `--bootstrap` creates `.venv` in the workspace and installs the skill's pinned dependencies. Omit it to install only the files.

- [Documentation](https://github.com/AAO-SH/codex-arena/blob/main/README.md)
- [Installation and distribution](https://github.com/AAO-SH/codex-arena/blob/main/references/packaging.md)
- [Source code](https://github.com/AAO-SH/codex-arena)

An [AAO.sh](https://aao.sh) project. [arena.aao.sh](https://arena.aao.sh) · MIT License.
