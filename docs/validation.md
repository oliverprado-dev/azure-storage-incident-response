# Evidências de validação

Execução local em 9 de novembro de 2026, com Python 3.12, Terraform 1.17.1 e AzureRM 4.66.0.

## Simulação local

```bash
PYTHONPATH=src python3 scripts/demo.py
```

O trecho abaixo resume a saída JSON do script. O ID terminado em `101` é o evento da escrita do operador. O ID terminado em `102` simula a escrita da própria função. Ambos seguem o contrato do [evento sintético](../fixtures/resource-write-success.json).

| Ordem | Sinal ou leitura simulada | Decisão e estado |
| --- | --- | --- |
| 1 | GET inicial do simulador | `allowBlobPublicAccess=false` |
| 2 | Operador aplica `true` e chega `ResourceWriteSuccess` (evento `101`) | `data.operationName=Microsoft.Storage/storageAccounts/write` |
| 3 | Handler em dry-run recebe `101` | `detect / would_remediate`, valor `true` |
| 4 | Handler em modo ativo reprocessa `101` | `remediate / verified`, GET final `false` |
| 5 | Chegam a duplicata de `101` e o evento `102` | Ambos `no_action / compliant`, total de um PATCH simulado |

## Verificações executadas

| Comando na raiz do repositório | Resultado observado |
| --- | --- |
| `PYTHONPATH=src python3 -m unittest discover -s tests -v` | 18 testes passaram. Incluem escopo, dry-run, correção, retentativa, duplicata, evento da própria correção, erro 403 e payload ARM |
| `ruff check src tests scripts` e `ruff format --check src tests scripts` | Lint e formatação passaram |
| `python3 -m pip install --require-hashes -r src/requirements.txt` e `python3 -m pip check` | Dependências instaladas em ambiente limpo com hashes e sem conflitos |
| `pip-audit --require-hashes -r src/requirements.txt` | Sem vulnerabilidades conhecidas reportadas na execução |
| Etapa **Verify the Azure Functions binding and source package** do [workflow](../.github/workflows/ci.yml) | SDK decodificou o evento sintético e invocou `GuardStorage` em dry-run com ARM simulado. ZIP da Function e sintaxe do script de deploy passaram |
| `terraform -chdir=infra fmt -check -recursive` e `terraform -chdir=infra init -backend=false -input=false -lockfile=readonly` | Formatação passou e a instalação do AzureRM correspondeu ao lock |
| `terraform -chdir=infra validate` e `terraform -chdir=infra test` | O ambiente bloqueou a criação de socket Unix pelo processo do AzureRM. O CI inclui os dois comandos |
| `trivy config --disable-telemetry --skip-version-check --skip-dirs infra/.terraform --tf-vars infra/terraform.tfvars.example --severity HIGH,CRITICAL --exit-code 1 infra` | Zero achados altos ou críticos fora das duas exceções por recurso documentadas em [arquitetura](architecture.md#identidades-e-permissões) |
| `gitleaks dir --redact --exit-code 1 .` e `gitleaks git --redact --exit-code 1` | Nenhum segredo detectado no conteúdo ou no histórico local |
| `actionlint .github/workflows/ci.yml` | Workflow passou na validação estática |

## Validação pendente em uma assinatura Azure

Execute o [roteiro de implantação](deployment.md) em uma assinatura de laboratório e preserve as evidências.

- Aplique o Terraform e confirme região, quotas, criação dos recursos, propagação de RBAC e indexação do trigger após One Deploy.
- Confirme a entrega com os filtros aplicados e a ingestão de `AppTraces` com o principal gerenciado. Correlacione a escrita do operador com o Activity Log.
- Em dry-run, observe `would_remediate` com a propriedade ainda `true`. Depois de ativar o modo de correção, repita o desvio e verifique `verified` e o GET independente com `false`. Confirme o contêiner privado e a rede pública desabilitada.
- Verifique retentativas e dead-letter em uma falha controlada. Aplique a pausa, confira o modo e a remoção da atribuição de escrita e desmonte o grupo ao final.

A execução hospedada do workflow acontece após o primeiro push. Os exemplos desta entrega registram execução local e saídas sintéticas.
