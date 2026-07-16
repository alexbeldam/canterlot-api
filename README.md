<p align="center">
  <img src="src/canterlot/static/favicon.svg" width="100" alt="Canterlot Logo">
</p>

<h1 align="center"><strong>Canterlot API 🌙</strong></h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/uv-F15A24?style=for-the-badge&logo=rust&logoColor=white" />
  <img src="https://img.shields.io/badge/Just-000000?style=for-the-badge&logo=gnu-bash&logoColor=white" />
  <img src="https://img.shields.io/badge/Ruff-FCC21B?style=for-the-badge&logo=python&logoColor=black" />
  <img src="https://img.shields.io/badge/License-BSL_1.1-333333?style=for-the-badge&logo=gnu&logoColor=white" />
</p>

<p align="center">
 <a href="#sobre-o-projeto">Sobre o Projeto</a> •
 <a href="#logica-de-funcionamento">Lógica de Funcionamento</a> •
 <a href="#primeiros-passos">Primeiros Passos</a> •
 <a href="#rotas-principais">Rotas Principais</a> •
 <a href="#roadmap">Roadmap</a> •
 <a href="#frontend">Frontend</a>
</p>

<br/>

<h2 id="sobre-o-projeto">📖 Sobre o Projeto</h2>

O **CanterlotAPI** é o motor backend para um aplicativo moderno de gestão de clubes do livro. Hoje ele cobre a criação e administração de clubes, o convite e gerenciamento de membros com hierarquia de papéis, o catálogo colaborativo de sugestões de livros, e a conta/perfil de cada usuário (autenticação por senha ou Google, troca de senha, e histórico pessoal de leitura).

A orquestração de rodadas de leitura em si (votação ranqueada ou sorteio randômico) está **planejada, mas ainda não implementada** — veja o [Roadmap](#roadmap) mais abaixo para o que já está desenhado mas ainda não construído.

<h2 id="logica-de-funcionamento">🧠 Lógica de Funcionamento</h2>

O sistema é guiado por dois pilares de regras de negócio fundamentais, já implementados, que gerenciam a dinâmica de convivência dos leitores:

- **Controle de Acesso Concorrente e Hierárquico:** Cada workspace de clube possui papéis bem definidos (`OWNER`, `ADMIN`, `MEMBER`). Ações administrativas — gerenciamento de cargos, remoção/banimento de membros, transferência de posse — seguem uma cadeia estrita de comando: um `ADMIN` nunca pode agir sobre outro `ADMIN` ou o `OWNER`, blindando o clube contra ações não autorizadas.
- **Gestão Autónoma de Admissão:** A entrada de novos participantes é controlada por convites emitidos pelo clube — um link público (rotacionável a qualquer momento) ou um convite direto por e-mail. Administradores mantêm controle total sobre o fluxo de novos membros, incluindo aprovação manual em clubes restritos e banimento.

A orquestração de sessões de leitura (curadoria → deliberação → acompanhamento de progresso) é o próximo pilar planejado — o catálogo colaborativo já existe hoje como a etapa de curadoria; deliberação (voto/sorteio) e acompanhamento de progresso ainda não foram construídos (ver [Roadmap](#roadmap)).

---

<h2 id="primeiros-passos">🚀 Primeiros Passos</h2>

Nossa stack utiliza o gerenciador de pacotes **`uv`** e o command runner **`just`**.

### Pré-requisitos

1. [uv](https://github.com/astral-sh/uv)
2. [Just](https://github.com/casey/just)
3. [Docker Desktop](https://www.docker.com/)

### Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/alexbeldam/canterlot-api.git
cd canterlot-api

# 2. Rode o Setup Automatizado
# Este comando verifica suas ferramentas, sobe os containers (Mongo/Redis),
# cria o arquivo .env e instala todas as dependências em milissegundos.
just setup

# 3. Preencha suas credenciais
# Abra o arquivo `.env` recém-criado e insira suas chaves (Google Books, JWT_SECRET, etc).
```

### Inicialização e Testes

Toda a gestão do projeto é centralizada via `just`. Você não precisa ativar virtual environments manualmente.

| Comando       | Descrição                                                                              |
| ------------- | -------------------------------------------------------------------------------------- |
| `just dev`    | Inicia o servidor Uvicorn com live-reload (`localhost:8000`)                           |
| `just verify` | Roda o pipeline completo (Lints, Tipagem, Imports, Complexidade e Testes de Cobertura) |
| `just test`   | Executa a suíte de testes isolada via Pytest                                           |
| `just format` | Aplica as correções automáticas de formatação (Ruff)                                   |

---

<h2 id="rotas-principais">📍 Endpoints Principais da API</h2>

A documentação interativa e completa (Swagger UI) fica disponível em `/docs` com o servidor rodando — é sempre a fonte da verdade sobre o contrato exato de cada rota. A tabela abaixo reflete apenas o que está **realmente implementado hoje**, com testes automatizados. Todas as rotas são montadas sob o prefixo `/v1`.

### Autenticação

Rotas protegidas exigem um header de autorização: `Authorization: Bearer <token>`. O access token é devolvido no corpo da resposta; o refresh token nunca aparece no corpo — ele é setado como cookie `httpOnly`, `Secure`, `SameSite=Strict`, restrito ao path `/auth`, e não deve ser lido ou manipulado pelo frontend.

| Rota                                     | Descrição                                                                                                                     |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| <kbd>POST /users</kbd>                   | Cria uma nova conta com usuário/senha, com suporte a convite embutido no corpo.                                              |
| <kbd>POST /auth/sessions</kbd>           | Cria uma sessão (login por senha ou OAuth, discriminado pelo campo `type: PASSWORD \| OAUTH` no corpo) — devolve o access token; o refresh token é setado como cookie. Para OAuth, o status code distingue o resultado: `200` login em conta existente, `201` conta nova criada, `409` quando a identidade já pertence a uma conta com outro método de login (é preciso logar por lá e então vincular este provedor). |
| <kbd>PUT /auth/sessions/current</kbd>    | Rotaciona o refresh token (lido do cookie) e emite um novo access token e um novo cookie.                                    |
| <kbd>DELETE /auth/sessions/current</kbd> | Encerra a sessão atual e limpa o cookie de refresh (idempotente — também retorna sucesso se não havia sessão ativa).         |

Há ainda uma rota oculta `POST /auth/login` (form-encoded, fora do schema OpenAPI) que existe apenas para alimentar o fluxo "Authorize" nativo do Swagger UI — não é uma via pública alternativa de login, e clientes reais devem sempre usar `POST /auth/sessions`.

### Perfil & Conta

| Rota                                                    | Descrição                                                                                                            |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| <kbd>PATCH /users/me</kbd>                              | Atualiza nome de exibição e/ou nome de usuário.                                                                     |
| <kbd>PUT /users/me/password</kbd>                       | Troca a senha (ou define a primeira senha de uma conta só-OAuth); revoga sessões antigas e devolve um novo access token (novo cookie de refresh). |
| <kbd>GET /users/me/auth-providers</kbd>                 | Lista provedores de login conectados e se há senha cadastrada.                                                       |
| <kbd>POST /users/me/auth-providers/{provider}</kbd>     | Vincula um novo provedor OAuth à conta autenticada.                                                                   |
| <kbd>DELETE /users/me/auth-providers/{provider}</kbd>   | Desvincula um provedor OAuth (bloqueado se for a única forma de login restante).                                     |
| <kbd>PUT /users/me/read-books/{identifier}</kbd>        | Marca um livro como lido no histórico pessoal do usuário.                                                            |

### Clubes & Controle de Acesso

| Rota                                                         | Descrição                                                                 |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| <kbd>POST /clubs</kbd>                                       | Cria um novo clube (autor = `OWNER`).                                        |
| <kbd>GET /clubs/{slug}</kbd>                                 | Detalhes do clube; aprovações pendentes visíveis só para `OWNER`/`ADMIN`.    |
| <kbd>PATCH /clubs/{slug}/settings</kbd>                      | Atualiza configurações do clube (nome, descrição, política de entrada, idiomas). |
| <kbd>DELETE /clubs/{slug}</kbd>                              | Dissolve e apaga o clube (somente `OWNER`).                                  |
| <kbd>POST /clubs/{slug}/invites</kbd>                        | Cria um convite público ou direto (corpo discriminado por `type`).          |
| <kbd>GET /clubs/{slug}/invites/public</kbd>                  | Retorna o link de convite público ativo do clube.                           |
| <kbd>PATCH /clubs/{slug}/pending-approvals/{user}</kbd>      | Aprova uma solicitação pendente de entrada (clube restrito).                |
| <kbd>DELETE /clubs/{slug}/pending-approvals/{user}</kbd>     | Rejeita uma solicitação pendente de entrada.                                |
| <kbd>DELETE /clubs/{slug}/members/me</kbd>                   | O próprio membro sai do clube.                                              |
| <kbd>DELETE /clubs/{slug}/members/{user}</kbd>               | Remove (e bane) um membro — `Engine de Rank Protection` aplicado.           |
| <kbd>PUT /clubs/{slug}/members/{user}/role</kbd>             | Promove ou rebaixa um membro.                                               |
| <kbd>POST /clubs/{slug}/ownership-transfers</kbd>            | Inicia a transferência de posse do clube para outro membro.                |
| <kbd>DELETE /clubs/{slug}/ownership-transfers/current</kbd>  | Reclama a posse de volta, dentro da janela de 24h.                          |

### Convites

| Rota                                            | Descrição                                                                    |
| -------------------------------------------------- | --------------------------------------------------------------------------------- |
| <kbd>GET /invites/{invite_id}/preview</kbd>     | Pré-visualiza um convite (nome do clube, tipo) antes de decidir aceitar.        |
| <kbd>PATCH /invites/{invite_id}</kbd>           | Aceita um convite — entrou direto, ficou pendente de aprovação, ou banido.       |

### Catálogo

| Rota                                                     | Descrição                                        |
| ------------------------------------------------------------ | --------------------------------------------------- |
| <kbd>POST /clubs/{slug}/catalog</kbd>                    | Sugere um livro ao catálogo do clube.              |
| <kbd>GET /clubs/{slug}/catalog</kbd>                     | Lista o catálogo do clube, paginado e ordenável.   |
| <kbd>DELETE /clubs/{slug}/catalog/{identifier}</kbd>     | Remove um livro do catálogo do clube.              |

### Livros

| Rota                                             | Descrição                                                                                |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| <kbd>GET /books/external</kbd>                   | Busca livros na Google Books API (requer `club_slug`, já que toda busca existe para alimentar um clube). |
| <kbd>GET /books/external/{identifier}</kbd>      | Detalhes de um livro direto do provedor externo, sem persistir.                             |
| <kbd>GET /books/{identifier}</kbd>               | Detalhes de um livro já persistido (ISBN ou id do provedor); `404` se ainda não existir na base — busca ao vivo é só via `/books/external`. |

---

<h2 id="roadmap">🗺️ Roadmap</h2>

Funcionalidades com as regras de negócio já desenhadas, mas **ainda não implementadas**:

- **Sessões de Leitura & Votação:** o ciclo completo de rodadas de leitura — iniciar uma rodada (sorteio automático ou pool curado), votação ponderada por membro, acompanhamento de progresso individual, e conclusão/cancelamento da rodada.
- **Verificação e troca de e-mail:** confirmação de e-mail no cadastro, e um fluxo para trocar o e-mail de uma conta existente.
- **Perfil estendido:** consultar o próprio perfil (hoje só é possível atualizá-lo, não vê-lo) e o perfil de outro membro do mesmo clube; consultar e remover entradas do histórico de leitura pessoal (hoje só é possível adicionar).
- **Logout de todos os dispositivos:** encerrar todas as sessões ativas de uma vez, como ação deliberada e independente da troca de senha.
- **Lembretes automáticos de prazo de leitura:** notificação por e-mail um dia antes e no dia do prazo de uma rodada, disparado por um cron externo.
- **Seleção de avatar:** gerado automaticamente, importado do Google, ou via Gravatar. Upload de imagem própria **não está nos planos** — o projeto não possui infraestrutura de armazenamento de arquivos.

Vinculação de pontes sociais externas (Discord/WhatsApp) foi cogitada, mas **descartada**: hoje não há forma de verificar se um link enviado por um administrador de clube leva a um conteúdo apropriado, e sem uma equipe de moderação, o risco de abuso (conteúdo impróprio, malware, spam) foi considerado inaceitável.

---

<h2 id="frontend">🖥️ Frontend</h2>

O frontend que consome esta API pode ser encontrado neste repositório:  
👉 **[https://github.com/alexbeldam/canterlot](https://github.com/alexbeldam/canterlot)**

---

<h2 id="licenca">📄 Licença</h2>

Este projeto está licenciado sob a **Business Source License 1.1 (BSL)**. Isto significa que qualquer pessoa pode usar, modificar e redistribuir este código, inclusive para fins comerciais, **exceto** para operar um serviço hospedado concorrente que ofereça funcionalidade de clube de leitura substancialmente similar à do Canterlot a terceiros.

Essa restrição converte-se automaticamente, na "Change Date" especificada no ficheiro [LICENSE](LICENSE), na **GNU Affero General Public License v3 (AGPLv3)**: irrestrita e totalmente de código aberto, incluindo a obrigação de manter aberto o código-fonte de qualquer modificação hospedada em rede (SaaS).

---

<p align="center">Feito com ⭐</p>
