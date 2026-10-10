# Codex Arena

![Codex Arena](https://raw.githubusercontent.com/AAO-SH/codex-arena/main/assets/codex-arena-logo.png)

Coloque estratégias à prova e transforme os melhores métodos em playbooks reutilizáveis para o Codex. Compare estratégias, modelos e esforços em tarefas recorrentes, com configuração e resultados locais ao seu projeto.

Requer Python 3.11+. O comando npm também requer Node.js 22+. A instalação do pacote não inicia torneios nem instala as dependências de execução automaticamente.

```bash
npx @aao-sh/codex-arena install --workspace . --bootstrap
uvx --from codex-arena codex-arena install --workspace . --bootstrap
```

Execute dentro do projeto desejado; `--workspace .` usa a pasta atual. `--bootstrap` prepara `.venv` no workspace e instala as dependências fixadas da skill. Omita essa opção para instalar somente os arquivos.

- [Documentação](https://github.com/AAO-SH/codex-arena/blob/main/README.md)
- [Instalação e distribuição](https://github.com/AAO-SH/codex-arena/blob/main/references/packaging.md)
- [Código-fonte](https://github.com/AAO-SH/codex-arena)

Uma iniciativa da [AAO.sh](https://aao.sh). [arena.aao.sh](https://arena.aao.sh) · Licença MIT.
