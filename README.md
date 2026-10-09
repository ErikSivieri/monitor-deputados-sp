# Monitor de Deputados SP

Coleta diária de dados públicos sobre a bancada paulista na Câmara dos Deputados e sobre os deputados estaduais da ALESP, desde 2015, para alimentar um painel de estudo pessoal.

**Fontes**
- Câmara dos Deputados: API e arquivos de Dados Abertos (cadastro, histórico de partido e exercício, cota parlamentar, proposições, votações nominais).
- ALESP: Portal de Dados Abertos (deputados, despesas de gabinete, proposituras, autores, tramitação, presença em comissões).
- TSE: Portal de Dados Abertos (candidaturas e bens declarados de 2014, 2018 e 2022).

**Como funciona**
`python -m coletor` baixa e agrega tudo em `data/painel.json`. O GitHub Actions roda isso todo dia às 6h (Brasília). Anos já encerrados ficam em `data/cache/` e só são recoletados aos domingos ou no dia 1º, para não sobrecarregar os servidores públicos. O diagnóstico de cada execução fica em `data/status.json`.
