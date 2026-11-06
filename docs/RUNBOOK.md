# 🛠️ Runbook — operação da Maratona de Melancias

Guia curto para quem vai colocar no ar, manter e resolver problema durante o
evento.

---

## 1. Rodar local (2 minutos)

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m streamlit run app.py
```

Ou `make install && make run`. Abre em <http://localhost:8501>.

Sem `.env`, o app já funciona: snapshot embutido, geo tolerante, log desligado
até o consentimento.

---

## 2. Deploy no Streamlit Community Cloud

1. **GitHub**: repositório com `app.py`, `requirements.txt`, `.streamlit/config.toml`.
2. **share.streamlit.io** → *New app* → branch `main` → **Main file path: `app.py`**.
3. **Settings → Secrets** (TOML):

```toml
ADMIN_PASSWORD = "troque-esta-senha"
MARATONA_DB = "/mount/dados/maratona.db"
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/<ID>/export?format=csv&gid=1904051669"
GEO_MODE = "block"
ALLOWED_COUNTRIES = "BR"
UNKNOWN_COUNTRY_POLICY = "allow"
CONSENT_REQUIRED = "1"
RETENTION_DAYS = "90"
```

4. **Reboot** o app depois de salvar segredos.

### Persistência do log

O disco do Community Cloud é **efêmero**: cada deploy/restart pode zerar o
`.db`. Opções, em ordem de esforço:

1. aceitar o reset e exportar CSV antes de cada deploy (painel → *Baixar log*);
2. montar volume persistente e apontar `MARATONA_DB` para ele;
3. trocar o backend: reimplementar `AnalyticsStore` com Postgres/Turso mantendo
   os métodos `log`, `rows`, `purge`, `delete_sid`, `session_paths`.

O app mostra um aviso vermelho no painel quando está em modo memória
(`store.degraded = True`), então dá para perceber na hora.

---

## 3. Atualizar a escala

**Opção A (recomendada) — ao vivo:** publique a aba *Alocações* como CSV
(*Arquivo → Compartilhar → Publicar na web → CSV*) e cole o link em
`SHEET_CSV_URL`. O app recarrega a cada 10 minutos (`st.cache_data(ttl=600)`).

Formato esperado do CSV:

```
Nome,ID atividade,Data,Início,Fim,Atividade,Local,Horas
```

**Opção B — snapshot:** edite `DATASET_JSON` no `app.py` com um JSON no formato
`{"monitores": [...], "atividades": [...], "cronograma": [...]}`.

Se qualquer coisa der errado, o app cai no snapshot embutido. Nada de tela branca.

---

## 4. Regra de acesso ao Brasil

| Cenário | O que fazer |
| --- | --- |
| País não é identificado (comum atrás de proxy) | manter `UNKNOWN_COUNTRY_POLICY=allow` |
| Precisa bloquear de verdade | `GEO_MODE=block` + `UNKNOWN_COUNTRY_POLICY=block` |
| Está atrás de Cloudflare | os cabeçalhos `CF-IPCountry` já vêm prontos |
| Sem CDN (Streamlit Cloud) | configurar `GEO_LOOKUP_URL=https://ipapi.co/{ip}/country/` |
| Suspeita de VPN | `ENABLE_IP_INTEL=1` (best-effort) |

**Teste rápido:** acesse de um celular no 4G (Brasil) e de uma VPN (outro país).
Se os dois caírem no mesmo resultado, revise a configuração de cabeçalhos.

> Aviso: nenhuma checagem por IP é infalível. Documente no aviso do evento que
> quem for bloqueado por engano deve falar com a organização.

---

## 5. Pixel e cookie

- Cookie: ligado junto com o consentimento (`COOKIE_DAYS`, padrão 30).
- Pixel: só existe com `ANALYTICS_PIXEL_URL`. Use um endpoint **próprio**
  (Cloudflare Worker, Apps Script, seu backend) que registre `e`, `s`, `p`, `t`.
- Para desligar tudo: `CONSENT_REQUIRED=1` (padrão) e `ANALYTICS_PIXEL_URL` vazio.

---

## 6. Painel da organização

- Só aparece na navegação se `ADMIN_PASSWORD` estiver definida.
- Mostra: sessões, identificadas, % de caminho completo, fora de ordem, funil por
  tela, maior abandono, caminho de cada sessão, bloqueios por país.
- Manutenção: aplicar retenção, baixar CSV, apagar tudo.

**Rotacionar a senha:** altere o secret e reinicie o app. Sessões já
autenticadas continuam válidas até o fim da sessão do navegador.

---

## 7. Testes antes de publicar

```bash
make check      # ruff + 224 testes
make cov        # cobertura (falha abaixo de 80%)
```

Checklist de pré-deploy:

- [ ] `make check` verde
- [ ] `ADMIN_PASSWORD` definida (e forte)
- [ ] `SHEET_CSV_URL` responde (abra no navegador)
- [ ] aviso de privacidade lido pela organização
- [ ] teste em celular (a maioria das melancias vai usar celular)
- [ ] log/backup exportado se o disco for efêmero

---

## 8. Incidentes comuns

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| "Acesso restrito" para todo mundo | `UNKNOWN_COUNTRY_POLICY=block` sem CDN | trocar para `allow` ou configurar `GEO_LOOKUP_URL` |
| Log zera a cada deploy | disco efêmero | volume persistente ou Postgres |
| Painel não aparece | `ADMIN_PASSWORD` vazia | definir secret e reiniciar |
| Nomes errados/desatualizados | CSV publicado antigo | republicar a aba e aguardar 10 min |
| Foto não aparece | > `MAX_PHOTO_MB` ou formato | reduzir/JPEG/PNG |
| Sessões duplicadas | cookie bloqueado no navegador | normal; o log conta sessões novas |
| App lento | planilha gigante | usar CSV enxuto (só colunas necessárias) |

---

## 9. Backup e exclusão

- **Backup:** painel → *Baixar log (CSV)*. Guarde fora do repositório.
- **Exclusão individual:** a própria pessoa faz em *Privacidade*.
- **Exclusão total:** painel → *Apagar tudo* (irreversível).
- **Retenção:** aplicada automaticamente a cada sessão nova; também há botão manual.

---

## 10. Contatos

- Dono do deploy: organização da Maratona.
- Dúvidas de LGPD: ver `docs/PRIVACIDADE.md`.
- Bug: abra issue com o texto do expander "Detalhes técnicos" e a tela em que ocorreu.
