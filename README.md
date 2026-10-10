<div align="center">
  <a href="https://arena.aao.sh"><img width="680" src="assets/codex-arena-logo.png" alt="Codex Arena — two rival mascots, blue and red, facing off before a coliseum" /></a>
</div>

<p align="center">
  <strong>Put strategies to the test. Turn the best ones into playbooks for your Codex.</strong>
</p>

<p align="center">
  <a href="https://github.com/AAO-SH/codex-arena"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-AAO--SH%2FCodex--Arena-181717?style=for-the-badge&logo=github" /></a>
  <a href="https://github.com/AAO-SH/codex-arena/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/AAO-SH/codex-arena?style=for-the-badge&logo=github&color=gold" /></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/github/license/AAO-SH/codex-arena?style=for-the-badge" /></a>
  <a href="https://github.com/AAO-SH/codex-arena/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/AAO-SH/codex-arena/tests.yml?branch=main&label=Tests&style=for-the-badge&logo=githubactions" /></a>
  <br />
  <a href="https://www.npmjs.com/package/@aao-sh/codex-arena"><img alt="Monthly npm downloads" src="https://img.shields.io/npm/dm/%40aao-sh%2Fcodex-arena?style=for-the-badge&logo=npm&label=npm%20per%20month" /></a>
  <a href="https://pypi.org/project/codex-arena/"><img alt="Monthly PyPI downloads" src="https://img.shields.io/pypi/dm/codex-arena?style=for-the-badge&logo=pypi&label=PyPI%20per%20month" /></a>
  <img alt="Python 3.11 or later" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <br /><br />
  <a href="https://arena.aao.sh"><img alt="Official website" src="https://img.shields.io/badge/Website-arena.aao.sh-2F5BFF?style=for-the-badge" /></a>
  <a href="https://telegram.aao.sh"><img alt="Telegram community" src="https://img.shields.io/badge/Telegram-Join-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" /></a>
  <a href="https://discord.aao.sh"><img alt="Discord community" src="https://img.shields.io/badge/Discord-Join-5865F2?style=for-the-badge&logo=discord&logoColor=white" /></a>
</p>

<hr />

**Your agent can learn a better way to work.** Codex Arena compares strategies in tournaments and turns winning methods into playbooks: practical guides with automations that Codex can reuse in your project. Before you activate them, it measures results on unseen tasks.

## Why use it

- **Find methods that work again.** Compare quality, time, and resource use on recurring tasks.
- **Carry what you learn into the next job.** Reuse instructions, scripts, and checks in playbooks.
- **Keep spending under control.** Plan the competition and set limits before running it.
- **Keep knowledge in the project.** Consult local memory, evidence, and history when you need them.

## Get started in your project

Open the folder where you want to use Arena and ask Codex:

```text
Install Codex Arena in this workspace:
https://github.com/AAO-SH/codex-arena
Use --bootstrap and check the environment with doctor.
Show me the plan before starting any tournament.
```

Installation is local to the project and does not start a competition. You choose the folder; there is no required path.

<details>
<summary><strong>Prefer the terminal? Install with npm, PyPI, or GitHub</strong></summary>

Requires **Python 3.11+**. npm is an alternative way to run the Python installer; it also requires **Node.js 22+**. Run the commands from the workspace you want to use. `--workspace .` means “this folder”; you can omit the option or provide any relative or absolute path in quotes.

### npm

```bash
npx @aao-sh/codex-arena install --workspace . --bootstrap
```

### PyPI

With [uv](https://docs.astral.sh/uv/), run it without installing the command globally:

```bash
uvx --from codex-arena codex-arena install --workspace . --bootstrap
```

Or install the command in a Python environment of your choice:

```bash
python -m pip install codex-arena
codex-arena install --workspace . --bootstrap
```

> The npm and PyPI packages are available as version 1.0.0. Package badges use registry-reported data and may take some time to display statistics for new packages.

### From GitHub

In the folder where you want to keep the Arena code:

```bash
git clone https://github.com/AAO-SH/codex-arena.git
cd codex-arena
```

Run the installer and point it to your project folder, wherever it is:

```bash
python scripts/arena.py install --workspace "../your-workspace" --bootstrap
```

The path above is just a relative example. The installer creates the destination if needed, copies the skill to `.agents/skills/codex-arena`, preserves existing configuration, and adds its configuration block to `.codex/config.toml`. `--bootstrap` prepares `.venv` with pinned dependencies.

### Verify the installation

Open a terminal in the installed project folder.

**Windows / PowerShell:**

```powershell
.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py doctor --json
.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py plan
```

**Linux / macOS:**

```bash
.venv/bin/python .agents/skills/codex-arena/scripts/arena.py doctor --json
.venv/bin/python .agents/skills/codex-arena/scripts/arena.py plan
```

To roll back the installation, run the installer from the clone or package with `install --rollback --workspace "path/to/workspace"`. See [Installation and recovery](references/execution.md) and [npm/PyPI distribution](references/packaging.md).

</details>

## From competition to playbook

**Compare → learn → validate → reuse.** Choose a task family, put different approaches to the test, and bring approved methods into your everyday work.

<details>
<summary><strong>Compare strategies, models, and reasoning efforts</strong></summary>

A tournament has three stages plus an additional validation step:

| Stage | What happens |
|---|---|
| Battle Royal | Everyone competes; scores place participants into tiers. |
| Swiss | Each tier competes for spots in the final. |
| Double elimination | Ten-game series determine each tier's champion, with a second-chance round. |
| +1 validation | Each playbook is compared with a run without a playbook on unseen cases. |

The four tiers are **iron, copper, silver, and gold**. Arena distinguishes task failures, quality-based losses, and ties. Models and reasoning efforts must be compatible with the environment's catalog; the policy remains fixed throughout the campaign. [Rules, rubric, and scoring →](references/competition.md)

Use Arena for recurring tasks with observable criteria, such as validating JSON contracts or comparing development workflows with objective tests. A simple one-off task without criteria or reserved cases rarely warrants a tournament.

</details>

<details>
<summary><strong>Try a demo without paid inference</strong></summary>

In a repository clone, prepare the environment:

```bash
python -m venv .venv
```

Activate it with `.venv\Scripts\Activate.ps1` in PowerShell or `source .venv/bin/activate` on Linux/macOS. Then:

```bash
python -m pip install -r requirements.txt -c constraints.txt
python scripts/arena.py run --simulate --config examples/rules-smoke.json --cases examples/demo-suite.json --max-tokens 250000 --max-ms 180000
python scripts/arena.py status RUN_ID
python scripts/arena.py report RUN_ID --output report.json
python scripts/arena.py playbook build --demo --name json-contract-demo
python scripts/arena.py playbook verify json-contract-demo
```

Replace `RUN_ID` with the identifier returned by the run. The public examples demonstrate the contracts; **simulation does not measure real-world quality or authorize playbook activation**. [Verification evidence →](references/verification.md)

</details>

<details>
<summary><strong>Plan a real campaign and activate a playbook</strong></summary>

1. Copy [`assets/default-config.json`](assets/default-config.json) and adjust the rules, policies, criteria, and prices.
2. Prepare at least five competition cases (`split: train`) and five reserved cases (`split: holdout`), as described by the [case schema](schemas/cases.schema.json). Keep unseen cases out of prompts, memory, plugins, and indexes.
3. Run `doctor --json`, `models`, and `plan --config rules.json` to check capabilities and estimate the work.
4. Start with `run --config rules.json --cases suite.json --max-tokens N --max-ms N`, replacing `N` with the authorized limits.
5. Monitor with `status` and `report`. `resume` takes **total** limits; calls with uncertain completion require reconciliation before any decision to rerun.
6. Once the campaign is complete and champions have been selected in all four tiers, run `playbook build --from-run RUN_ID --name playbook-name --max-tokens N --max-ms N`.
7. Validate the frozen candidate with `playbook validate playbook-name --cases holdouts.json --tier all --max-tokens N --max-ms N`. Activate only approved tiers: `playbook activate playbook-name --tier gold`. View its instructions with `playbook show playbook-name`.

Validation requires at least five unseen cases and three repetitions per case and variant. The default of 100 contestants involves **4,950 matchups in Battle Royal alone**; review the plan and size the campaign before running it.

Real campaigns require an authenticated Codex CLI and a sandbox backend that enforces restricted reads. The legacy Windows sandbox may not meet this requirement; in those environments, Arena blocks dispatch. See the [execution requirements](references/execution.md) for a compatible backend.

Local limits control reservations and cumulative duration; they do not guarantee the provider's final billed amount. Costs based on API pricing are equivalent estimates. [Playbooks, validation, and plugins →](references/playbooks.md)

</details>

<details>
<summary><strong>Memory, plugins, commands, and project files</strong></summary>

Retrieve knowledge with local hybrid search and identified sources. Plugins add behaviors after compatibility checks. Knowledge documents and playbooks follow **OKF 0.2**; this showcase README does not require front matter.

| Commands | Purpose |
|---|---|
| `install`, `doctor`, `models`, `plan` | Installation, diagnostics, catalog, and planning |
| `run`, `resume`, `status`, `report`, `reconcile` | Execution, monitoring, and recovery |
| `playbook build/validate/activate/verify/show` | Build and use playbooks |
| `plugin check/enable/disable` | Compose behaviors |
| `memory download/index/search/graph` | Embeddings, search, and local knowledge |
| `keys rotate/revoke` | Keys and trust |

Use `python scripts/arena.py --help` in the clone. In an installed project, use the workspace's `.venv` Python with `.agents/skills/codex-arena/scripts/arena.py`.

| Workspace folder | Contents |
|---|---|
| `.agents/skills/codex-arena` | Installed skill |
| `.codex/arena` | Keys, approvals, and embedding cache |
| `.docs` | Documents and knowledge graph |
| `.memory/arena` | Local state and indexes |
| `.scratch/arena` | Runs, debates, and candidates |
| `.playbooks/<name>` | Playbooks and evidence |

[Memory and retrieval →](references/memory.md) · [Architecture and contracts →](references/architecture.md)

</details>

<details>
<summary><strong>Development, tests, and package publishing</strong></summary>

In the clone, with the Python environment activated:

```bash
python -m pip install -r requirements-dev.txt -r requirements-publish.txt
python -m pytest -q
```

Distribution tests also require Node.js 22+. The suite uses a simulated executor and does not run paid tournaments. CI covers Windows, Linux, and macOS with Python 3.11 and 3.12. See [verification evidence and limits](references/verification.md) and [building and publishing the packages](references/packaging.md).

</details>

## Community and acknowledgments

An [AAO.sh](https://aao.sh) initiative. Share ideas and experiences on [Telegram](https://telegram.aao.sh) and [Discord](https://discord.aao.sh), or contribute on [GitHub](https://github.com/AAO-SH/codex-arena).

Inspired by [Jake Schincariol's Arena](https://github.com/Jakeschincariol/arena-skill/tree/df07b8e518e10cdecd8cd7712d9958b6f396250e), with MIT attribution preserved. The presentation is aligned with [Fable Harness](https://github.com/AAO-SH/fable-harness). [Full credits](NOTICE.md) · [Technical sources](references/sources.md).

<br />

<p align="center">
  <a href="https://aao.sh">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/aao-logo.svg" />
      <img height="58" src="assets/aao-logo-light.svg" alt="AAO.sh" />
    </picture>
  </a>
  <br />
  Built and maintained by the <a href="https://github.com/AAO-SH/codex-arena/graphs/contributors">AAO.sh community</a>.<br />
  <a href="https://arena.aao.sh">arena.aao.sh</a> · <a href="LICENSE">MIT License</a>
</p>
