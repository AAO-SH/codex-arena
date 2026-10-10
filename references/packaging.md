---
type: Reference
title: Distribuição npm e PyPI
---

# Distribuição por npm e PyPI

Os pacotes `@aao-sh/codex-arena` e `codex-arena` incluem uma cópia fechada dos arquivos públicos da skill. A execução não baixa o código-fonte do repositório. O pacote npm requer Node.js 22 ou mais recente e procura Python 3.11 ou mais recente; `PYTHON` pode apontar para o executável desejado. O pacote Python declara `Requires-Python >=3.11` e não instala dependências automaticamente.

Instale a skill no workspace atual com uma das opções:

```bash
npx @aao-sh/codex-arena install --workspace . --bootstrap
uvx --from codex-arena codex-arena install --workspace . --bootstrap
```

Também é possível instalar o comando Python:

```bash
python -m pip install codex-arena
codex-arena install --workspace . --bootstrap
```

`--bootstrap` é uma escolha explícita que cria `.venv` no workspace e instala os requisitos Python fixados pela skill. Para instalar os arquivos sem baixar essas dependências, omita `--bootstrap`. O pacote não executa instalação, bootstrap ou torneios durante a instalação do npm ou do Python.

O launcher usa o Python que encontrou para executar os comandos. Depois do bootstrap, use o Python do `.venv` do workspace nos comandos que precisam das dependências de runtime, por exemplo `.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py run ...` no Windows ou `.venv/bin/python .agents/skills/codex-arena/scripts/arena.py run ...` em Linux e macOS.

Para criar localmente o tarball npm, a wheel e o source distribution a partir do manifesto público compartilhado:

```powershell
python packaging/build_distribution.py --output ".scratch/distributions"
```

O build requer Python 3.11 ou mais recente, npm e uma ferramenta de build Python. Instale as ferramentas fixadas com `python -m pip install -r requirements-publish.txt` ou use uv, que o script detecta quando o módulo `build` não está disponível. Ele cria os artefatos em `.scratch/distributions/npm` e `.scratch/distributions/pypi` e não os publica.

Valide a criação dos pacotes e a execução dos comandos instalados com:

```powershell
python -m pytest tests/test_packaging.py -q
```

Os testes requerem as dependências de `requirements-dev.txt`, Node.js e as ferramentas de build. Eles abrem os artefatos gerados, reconstroem uma wheel a partir do sdist e instalam os comandos em ambientes isolados com caminhos contendo espaços e Unicode.

## Publicação pelo GitHub Actions

O workflow [publish-package.yml](../.github/workflows/publish-package.yml) testa o código, constrói os três artefatos e verifica os metadados antes de publicar exatamente esses arquivos. Pode ser iniciado manualmente pela branch padrão, escolhendo `npm`, `pypi` ou `both`, ou pela publicação de uma release com tag `v<VERSÃO>`. A tag deve corresponder à versão do manifesto. Não sobrescreva versões já publicadas; avance a versão dos metadados e do CLI juntos.

Há duas formas de autenticação, configuradas pelo mantenedor:

- **Secrets do repositório:** `NPM_TOKEN`, com permissão de publicação no escopo `@aao-sh`, e `PYPI_API_TOKEN`, com permissão para o projeto Python. Um secret de outro repositório não é automaticamente compartilhado. Nunca adicione os valores aos arquivos do projeto.
- **Trusted Publishing:** configure no registro o proprietário `AAO-SH`, repositório `codex-arena`, workflow `publish-package.yml`, sem nome de environment. O workflow solicita `id-token: write` e usa OIDC quando não há token configurado. No npm, permita a ação de publicação direta.

O PyPI aceita um [publicador pendente](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) para criar um projeto na primeira publicação. No npm, o pacote precisa existir antes da configuração do publicador; a primeira versão requer login interativo ou um token autorizado. Consulte [Trusted Publishing do npm](https://docs.npmjs.com/trusted-publishers/) e [do PyPI](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

O workflow falha se a autenticação ou o envio falhar; não registra uma publicação omitida como sucesso. A publicação pode concluir em um registro e falhar no outro. Nesse caso, corrija a causa e execute novamente somente o registro pendente.
