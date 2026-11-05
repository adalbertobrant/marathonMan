# Briefing original (guardado como referência)

> Este é o pedido que originou o projeto, preservado sem edição. O `README.md`
> da raiz é o readme do projeto; este arquivo existe para manter o contexto.

---

# Ajudando para todos ficarem felizes

Crie uma aplicação com emojis e bem ao estilo das pessoas que tem hoje entre 20
anos e 25 anos e estão na universidade. Eles estão participando como
organizadores e Melancias (de bastante destaque aos melancias), inclusive crie
uma área de meditação onde eles possam colocar palavras positivas e enviarem
fotos que nao ficam guardadas no streamlit.

Eles precisam serem orientados e cuidados com afeto, para que executem as suas
tarefas que estão aqui
<https://docs.google.com/spreadsheets/d/1hWy4FJ8WvVwqsrp_-5EoKzksBq3F4TBBFDcIUCh4cPU/edit?gid=1904051669#gid=1904051669>

Essas tarefas devem estar disponibilizadas para todos só que eles possam ver o
resumo individual, assim eles não precisam navegar por inúmeras abas nem nada.

Crie a aplicação em streamlit, fazendo apenas um único arquivo, que vai ser
enviado para o meu github e depois colocado online.

No github deve ter o readme.md do projeto que não é esse, o arquivo
requirements.txt também.

Também coloque aqueles que vão ganhar mais horas em destaque e já dê os parabéns
em melancias em destaque.

---

## Complemento de escopo (segunda mensagem)

- log detalhado de quem entrou;
- não permitir VPN, apenas links provenientes do Brasil;
- registrar todas as telas usadas e se a pessoa fez o caminho correto;
- salvar um cookie;
- colocar um pixel transparente para acompanhar a navegação.

### Como o complemento foi atendido

| Pedido | Entrega |
| --- | --- |
| log detalhado de quem entrou | eventos por sessão (tela, ordem, tempo, nome, país) em SQLite, com painel da organização |
| só Brasil, sem VPN | decisão por país de saída + reputação de IP opcional (best-effort, documentado) |
| todas as telas e caminho correto | trilha de navegação comparada ao caminho canônico, com completude e primeira falha |
| cookie | cookie first-party `melancias_sid` com id aleatório, renovável |
| pixel transparente | pixel 1×1 opcional, declarado na política e disparado **só com consentimento** |

Duas decisões conscientes, explicadas em `docs/PRIVACIDADE.md`:

1. **nada de rastreamento oculto** — cookie e pixel só existem depois do "sim";
2. **"gravar telas" = trilha de navegação**, não gravação de vídeo/tela.
