# 🍉 Maratona de Melancias

Painel único da equipe de organização da maratona: cada **melancia** vê a própria
escala sem caçar aba no Google Sheets, todo mundo vê o mural de tarefas, os
destaques por horas ganham palmas — e ainda sobra um cantinho de meditação para
respirar entre um credenciamento e outro.

Feito em **Streamlit**, em **um único arquivo** (`app.py`), com testes
automatizados, dados reais da planilha oficial e privacidade por padrão (LGPD).

```
🍉 Início  ·  📅 Programação  ·  🙋 Quem é você?  ·  📋 Meu resumo
🗓️ Tarefas de todos  ·  🏆 Destaques  ·  🧘 Meditação  ·  🔐 Privacidade  ·  🛠️ Organização
```

---

## ✨ O que tem dentro

| Tela | O que resolve |
| --- | --- |
| **Início** | boas-vindas, números da maratona e atalhos para o caminho certo |
| **Programação** | grade oficial da Final SBC 2026 (05 a 08/11): os 4 dias, 34 momentos, locais, filtro por dia, destaque do que está acontecendo agora e **download .ics** |
| **Quem é você?** | busca tolerante a acento/caixa para a pessoa se identificar |
| **Meu resumo** | horas, funções, lista, reunião, próxima tarefa e a escala dos 3 dias com checkboxes |
| **Tarefas de todos** | mural completo com filtro por dia/busca, CSV para download e "só as minhas" |
| **Destaques** | pódio 🥇🥈🥉 por horas, parabéns, superlativos e todas as melancias com badges |
| **Meditação** | respiração 4-7-8, check-in emocional, mural de palavras e fotos **que não são salvas** |
| **Privacidade** | o que é medido, por quê, por quanto tempo — e botão para apagar tudo |
| **Organização** | funil, caminho de cada sessão, abandonos, bloqueios e manutenção (senha) |

**Destaques em melancias**: as 52 pessoas aparecem com badges de lista, horas,
funções e presença na reunião; as que mais somam horas ganham pódio e mensagem
de parabéns.

---

## 📅 Programação no calendário (.ics)

A tela **Programação** tem o botão **“Adicionar à minha agenda (.ics)”**. O
arquivo é gerado em memória (`build_ics()`), sem serviço externo, e traz:

- os **34 momentos** oficiais, com fuso `America/Sao_Paulo`, local e categoria;
- um evento extra em **14/11 às 09:00** com o recado guardado e **alarme 5
  minutos antes** (`VALARM`);
- cabeçalho `X-WR-CALNAME` para o calendário aparecer com nome no app de agenda.

O mesmo arquivo fica versionado em
[`docs/programacao-final-sbc-2026.ics`](docs/programacao-final-sbc-2026.ics)
para quem preferir baixar direto do repositório. Ele é reprodutível: rode
`make ics` sempre que a programação mudar — existe teste comparando o arquivo
publicado com o gerado (`test_arquivo_estatico_esta_sincronizado`).

No celular, toque no arquivo e escolha o calendário. No Google Agenda pelo
computador: **Configurações → Importar e exportar**.

---

## 🚀 Rodando local

```bash
# com uv (recomendado)
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py

# ou com pip
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
streamlit run app.py
```

Abre em <http://localhost:8501>. Sem nenhuma variável de ambiente o app já
funciona: dados embutidos, acesso liberado quando o país não é identificável e
registro **desligado** até a pessoa consentir.

---

## ☁️ Deploy no Streamlit Community Cloud

1. Suba o repositório no GitHub (só `app.py`, `requirements.txt`, `.streamlit/` e `docs/` são necessários).
2. Em <https://share.streamlit.io>, aponte **Main file path** para `app.py`.
3. Em **Settings → Secrets**, cole o conteúdo do seu `.env` em formato TOML:

```toml
ADMIN_PASSWORD = "uma-senha-boa"
MARATONA_DB = "/mount/dados/maratona.db"
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=1904051669"
ANALYTICS_PIXEL_URL = "https://seu-endpoint/pixel.gif"
```

> ⚠️ O disco do Community Cloud é **efêmero**: a cada deploy/restart o SQLite
> pode zerar. Para log persistente, use volume montado, ou troque o
> `AnalyticsStore` por Postgres/Turso (o contrato é `log`, `rows`, `purge`,
> `delete_sid`). O app avisa na tela quando está em modo memória.

---

## ⚙️ Configuração (tudo opcional)

| Variável | Padrão | Para quê |
| --- | --- | --- |
| `MARATONA_DB` | `.data/maratona.db` | caminho do SQLite de eventos |
| `GEO_MODE` | `block` | `off` desliga a regra de país |
| `ALLOWED_COUNTRIES` | `BR` | lista de países liberados |
| `UNKNOWN_COUNTRY_POLICY` | `allow` | o que fazer quando o país é desconhecido |
| `GEO_LOOKUP_URL` | vazio | lookup de país por IP (ex.: `https://ipapi.co/{ip}/country/`) |
| `ENABLE_IP_INTEL` | `0` | checagem best-effort de VPN/proxy/datacenter |
| `IP_INTEL_URL` | ip-api.com | endpoint usado quando `ENABLE_IP_INTEL=1` |
| `CONSENT_REQUIRED` | `1` | exige consentimento antes de registrar |
| `RETENTION_DAYS` | `90` | retenção automática dos eventos |
| `COOKIE_NAME` / `COOKIE_DAYS` | `melancias_sid` / `30` | cookie first-party da sessão |
| `ANALYTICS_PIXEL_URL` | vazio | pixel 1×1 opcional (só com consentimento) |
| `ADMIN_PASSWORD` | vazio | libera o painel da organização |
| `SHEET_CSV_URL` | vazio | CSV ao vivo da aba "Alocações" (fallback: snapshot) |
| `MAX_PHOTO_MB` | `8` | limite de upload na meditação |
| `TZ_NAME` | `America/Sao_Paulo` | fuso das telas e do "próxima tarefa" |

Modelo completo em [`.env.example`](.env.example).

---

## 📊 Dados da escala

O snapshot embutido em `app.py` veio da planilha oficial (52 melancias, 26
atividades, 13 blocos de cronograma, 891 horas somadas). Para manter ao vivo sem
tocar no código, defina `SHEET_CSV_URL` com o export CSV da aba **Alocações**
(`Nome, ID atividade, Data, Início, Fim, Atividade, Local, Horas`).

Se a planilha mudar de formato, o app **não quebra**: `normalize_dataset`
descarta linhas vazias, converte números e ordena; se o CSV falhar, cai no
snapshot embutido.

---

## 🔐 Privacidade, LGPD e as regras de acesso

O resumo honesto:

- **Log detalhado de quem entrou**: sim — tela aberta, ordem do caminho, tempo
  aproximado, nome escolhido e país. **Só depois do consentimento.**
- **Cookie**: sim, um cookie first-party com id aleatório de 128 bits (sem IP,
  sem nome dentro dele), para a sessão não reiniciar a cada refresh.
- **Pixel transparente 1×1**: implementado, mas **opcional e nunca oculto**:
  aparece na política, só dispara com consentimento e envia apenas id anônimo +
  tela + horário. Se `ANALYTICS_PIXEL_URL` estiver vazio, não existe pixel.
- **"Gravar todas as telas"**: registramos *quais telas e em que ordem* (e o
  tempo), **não** gravação de vídeo/tela. Gravação de sessão exigiria
  consentimento específico e ferramenta de terceiros — está fora do escopo de
  propósito.
- **Fotos da meditação**: ficam só na memória da sessão do navegador; os
  metadados (EXIF/GPS) são removidos antes de exibir; nada é escrito em disco.
- **VPN / "só Brasil"**: bloqueio por país de saída da conexão. É
  **best-effort** — VPN, rede universitária, CGNAT e proxy corporativo podem
  confundir a checagem. O app nunca grava IP, e a política de país desconhecido
  é configurável (padrão: liberar para não travar ninguém por engano).

Detalhes completos em [`docs/PRIVACIDADE.md`](docs/PRIVACIDADE.md) e na própria
tela **Privacidade** do app.

---

## 🧪 Testes e qualidade

```bash
make test    # 224 testes
make cov     # cobertura (89% do app.py)
make lint    # ruff
make check   # o que o CI roda
```

Pirâmide usada:

- **unitários** — dataset, busca, ranking, horários, funil, geo, store, imagens;
- **integração** — `AppTest` sobe o `app.py` de verdade e percorre todas as telas;
- **privacidade** — testes que garantem que palavra/foto não vão para o banco,
  que sem consentimento nada é gravado e que o pixel não vaza HTML;
- **robustez** — dataset vazio, banco corrompido, disco sem permissão, CSV ruim,
  escrita concorrente.

CI em [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda lint + testes
em Python 3.11 e 3.12 a cada push/PR.

---

## 🗂️ Estrutura

```
app.py                     aplicação inteira (único arquivo de app)
requirements.txt           dependências de produção
requirements-dev.txt       testes + lint
pyproject.toml             pytest, coverage e ruff
Makefile                   atalhos
.streamlit/config.toml     tema e configuração do servidor
.env.example               todas as variáveis, comentadas
docs/BRIEFING.md           pedido original, guardado como referência
docs/BACKLOG.md            épicos, histórias, critérios de aceite, sprints
docs/PRIVACIDADE.md        política de dados (LGPD)
docs/RUNBOOK.md            deploy, operação e incidentes
docs/programacao-final-sbc-2026.ics  programação pronta para importar
scripts/gerar_ics.py       regera o .ics publicado (make ics)
tests/                     224 testes
```

---

## 🤝 Metodologia

Cada tela nasceu de uma história de usuário com critérios de aceite (formato
Dado/Quando/Então) e definição de pronto que inclui teste automatizado e
checagem de privacidade. O backlog, as sprints e os riscos estão em
[`docs/BACKLOG.md`](docs/BACKLOG.md).

Contribuição: abra uma branch, rode `make check`, descreva o que mudou e o que
foi testado. Se mexer em coleta de dados, atualize `docs/PRIVACIDADE.md` no
mesmo PR.

---

Feito com afeto, melancia e tipografia arredondada. 🍉💚
