# Front-end

Base inicial em Next.js, React e TypeScript para consumir a API do dashboard.

## Rodar

```powershell
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

Acesse `http://localhost:3000`.

## Estrutura

- `src/app/`: páginas, layout e estilos globais.
- `src/components/`: componentes visuais reutilizáveis.
- `src/lib/api.ts`: cliente tipado da API FastAPI.
- `public/`: imagens, ícones e fontes estáticas.

Os blocos da página inicial são placeholders para você inserir gráficos, tabelas e regras visuais.
