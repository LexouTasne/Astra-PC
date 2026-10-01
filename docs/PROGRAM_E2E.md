# Program Generation E2E Benchmark

Este benchmark testa geração de programas reais, compilação/sintaxe e execução com casos de entrada/saída.

## Cenários

São 50 programas executáveis distribuídos entre Python, JavaScript/Node.js, Bash, C, C++ e Rust. Os cenários incluem gerenciamento de frota, estoque, CSV/JSON, logs, agenda/conflitos, filas, matemática, validação, agregações e pequenas tarefas de automação.

Também são gerados 5 scripts .bat. No host Linux atual não existe cmd.exe, Wine ou PowerShell, então esses scripts são apenas verificados estruturalmente e não contam como execução real.

## Runtime disponível no host

- Python 3
- Node.js
- Bash
- GCC
- G++
- Rust / rustc / cargo

Java, Go, Ruby, Lua, PHP, Wine/cmd e PowerShell não estavam disponíveis no host durante esta rodada.

## Resultado da rodada de 30/09/2026

Modelo gerador principal: qwen2.5-coder:3b.

Após geração, compilação/syntax check, execução de casos e uma tentativa automática de correção:

- 50 programas executáveis testados
- 25 passaram
- 25 falharam
- 5 .bat gerados e aprovados na inspeção estrutural
- 0 .bat executados, porque não há runtime Windows instalado

Principais classes de falha encontradas:

1. Uso incorreto de argv[0] / inclusão do nome do executável nos dados.
2. Parsing incorreto quando um único argumento contém vírgulas ou dois-pontos.
3. Formatação de saída diferente do contrato, apesar de lógica quase correta.
4. Ordenação ou desempate incorretos.
5. Headers/imports faltando em C/C++/Rust.
6. Interpretação incorreta de intervalos e agregações.
7. Código cercado por markdown em uma resposta C++.
8. Programas Rust usando APIs/traits incorretos.

A revalidação usa binários exclusivos por cenário (c_fleet, cpp_fleet, rust_fleet) para evitar colisão entre executáveis de linguagens diferentes.

## Executar

Gerar e testar novamente:

    PYTHONPATH=. .venv/bin/python -u benchmarks/program_generation_e2e.py

Revalidar apenas os fontes existentes, sem chamar modelo:

    PYTHONPATH=. .venv/bin/python -u benchmarks/revalidate_programs.py

Os artefatos e resultados ficam em:

    /home/lex/Astra-Real-E2E-50-final/

O resultado final da revalidação fica em revalidated.json.
