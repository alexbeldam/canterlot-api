<p align="center">
  <img src="https://img.icons8.com/color/128/000000/book.png" width="100" alt="Canterlot Logo">
</p>

<h1 align="center"><strong>Canterlot API 📚</strong></h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/MongoDB-47A248?style=for-the-badge&logo=mongodb&logoColor=white" />
  <img src="https://img.shields.io/badge/Redis-DC382D?style=for-the-badge&logo=redis&logoColor=white" />
  <img src="https://img.shields.io/badge/uv-F15A24?style=for-the-badge&logo=rust&logoColor=white" />
  <img src="https://img.shields.io/badge/Just-000000?style=for-the-badge&logo=gnu-bash&logoColor=white" />
  <img src="https://img.shields.io/badge/Ruff-FCC21B?style=for-the-badge&logo=python&logoColor=black" />
  <img src="https://img.shields.io/badge/License-AGPL_v3-333333?style=for-the-badge&logo=gnu&logoColor=white" />
</p>

<p align="center">
 <a href="#sobre-o-projeto">Sobre o Projeto</a> •
 <a href="#logica-de-funcionamento">Lógica de Funcionamento</a> •
 <a href="#primeiros-passos">Primeiros Passos</a> •
 <a href="#rotas-principais">Rotas Principais</a> •
 <a href="#frontend">Frontend</a>
</p>

<br/>

<h2 id="sobre-o-projeto">📖 Sobre o Projeto</h2>

O **CanterlotAPI** é o motor backend para um aplicativo moderno de gestão de clubes do livro. Ele cobre todo o ciclo de vida de um clube de leitura: desde a criação do grupo e rotação segura de convites, até a sugestão de livros no catálogo e a orquestração de sessões de leitura (via votação ranqueada ou sorteio randômico).

O foco é fornecer uma infraestrutura rápida e descentralizada para organizar leituras conjuntas, permitindo integrações com redes sociais externas (como Discord ou WhatsApp) para a comunicação direta dos membros.

<h2 id="logica-de-funcionamento">🧠 Lógica de Funcionamento</h2>

O sistema é guiado por quatro pilares de regras de negócio fundamentais que gerenciam a dinâmica de convivência e engajamento dos leitores:

- **Controle de Acesso Concorrente e Hierárquico:** Cada workspace de clube possui papéis bem definidos (`OWNER`, `ADMIN`, `MEMBER`). As ações administrativas cruciais — como gerenciamento de cargos, moderação de membros e controle do status das sessões de leitura — seguem uma cadeia estrita de comando para blindar o clube contra ações não autorizadas.
- **Gestão Autónoma de Admissão:** A entrada de novos participantes é controlada por chaves únicas de convite emitidas pelo clube. Administradores mantêm o controle total sobre o fluxo de novos membros, podendo rotacionar ou revogar credenciais de acesso público instantaneamente, mitigando entradas indesejadas sem afetar os membros ativos.
- **Ciclo de Vida da Sessão de Leitura:** O engajamento baseia-se em ciclos fechados divididos em três etapas sequenciais:
  - _Curadoria:_ Membros alimentam o catálogo sugerindo obras literárias com dados validados.
  - _Deliberação:_ A escolha do próximo livro da rodada pode ocorrer de forma democrática (votação ponderada por preferência) ou por sorteio automatizado.
  - _Metrificação:_ Durante a rodada ativa, o progresso individual de cada participante é monitorado pelo sistema para fornecer relatórios de engajamento em tempo real aos moderadores.
- **Integração de Comunicação Descentralizada:** Para manter o MVP focado no desempenho operacional de dados, a API não encapsula canais de mensagens internas, fornecendo em vez disso suporte nativo para vinculação direta de pontes sociais (links para servidores ou grupos externos), centralizando o ponto de encontro da comunidade.

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

A documentação interativa e completa (Swagger UI) fica disponível em `/docs` com o servidor rodando. Abaixo estão os contratos de negócio essenciais da arquitetura.

### Autenticação & Usuários

Rotas protegidas exigem um header de autorização: `Authorization: Bearer <token>`

| Rota                           | Descrição                                                              |
| ------------------------------ | ---------------------------------------------------------------------- |
| <kbd>POST /auth/register</kbd> | Cria uma nova conta de usuário. Pode receber um `invite_token` nativo. |
| <kbd>POST /auth/login</kbd>    | Autentica e devolve os tokens de acesso e refresh.                     |
| <kbd>POST /auth/refresh</kbd>  | Emite um novo Access Token sem exigir relogin manual.                  |
| <kbd>GET /users/me</kbd>       | Retorna o perfil completo e histórico do usuário autenticado.          |

### Clubes & Controle de Acesso

| Rota                                           | Descrição                                                      |
| ---------------------------------------------- | -------------------------------------------------------------- |
| <kbd>POST /clubs</kbd>                         | Cria um novo clube (Autor = `OWNER`).                          |
| <kbd>POST /clubs/{id}/invites/rotate</kbd>     | Invalida os links públicos antigos e gera um novo `shortuuid`. |
| <kbd>PUT /clubs/{id}/members/{user}/role</kbd> | Promove ou rebaixa membros (Engine de Rank Protection).        |
| <kbd>DELETE /clubs/{id}/members/{user}</kbd>   | Expulsa o membro e limpa seu acesso ao catálogo.               |

### Sessões de Leitura & Catálogo

| Rota                                         | Descrição                                                        |
| -------------------------------------------- | ---------------------------------------------------------------- |
| <kbd>GET /clubs/{id}/catalog/search</kbd>    | Faz proxy com a API do Google Books para buscar obras.           |
| <kbd>POST /clubs/{id}/catalog/suggest</kbd>  | Adiciona um livro ao repositório de leituras pendentes do clube. |
| <kbd>POST /clubs/{id}/sessions</kbd>         | Inicia uma nova rodada (`VOTE` ou `RANDOM`).                     |
| <kbd>POST /clubs/{id}/sessions/votes</kbd>   | Envia o array ranqueado de votos do membro para a rodada ativa.  |
| <kbd>GET /clubs/{id}/sessions/progress</kbd> | Retorna o mural atualizado de quem já concluiu a meta do mês.    |

---

<h2 id="frontend">🖥️ Frontend</h2>

O frontend que consome esta API pode ser encontrado neste repositório:  
👉 **[https://github.com/alexbeldam/canterlot](https://github.com/alexbeldam/canterlot)**

---

<h2 id="licenca">📄 Licença</h2>

Este projeto está licenciado sob a licença **GNU Affero General Public License v3 (AGPLv3)**. Isto significa que qualquer pessoa pode hospedar, modificar e interagir com este software, mas todas as modificações em ambientes de rede (SaaS) são **legalmente obrigadas** a manter o código-fonte aberto sob esta mesma licença.

Consulte o ficheiro [LICENSE](LICENSE) para obter mais detalhes.

---

<p align="center">Feito com 📖</p>
