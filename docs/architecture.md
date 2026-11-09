# Arquitetura e controles

## Contrato do evento

A fonte é o grupo de recursos do laboratório. O tópico de sistema usa `Microsoft.Resources.ResourceGroups` com localização `Global`, como exigido para essa fonte. A inscrição entrega `EventGridSchema` ao endpoint nativo `AzureFunction`, identificado pelo ID ARM completo da função `GuardStorage`. O provedor `Microsoft.EventGrid` precisa estar registrado para que o serviço possa obter a chave do trigger. [Tópicos de sistema](https://learn.microsoft.com/en-us/azure/event-grid/system-topics) · [Endpoint de Azure Functions](https://learn.microsoft.com/en-us/azure/event-grid/handler-functions)

| Filtro na inscrição | Requisito no handler |
| --- | --- |
| `Microsoft.Resources.ResourceWriteSuccess` | Mesmo `eventType`, com `dataVersion` igual a `2` e `eventTime` com fuso |
| Prefixo de `subject` igual ao ID ARM da conta | Igualdade exata de `subject` e `data.resourceUri` com o ID configurado. A comparação ignora maiúsculas e minúsculas |
| `StringIn` para `data.operationName` e `data.resourceUri` | Operação `Microsoft.Storage/storageAccounts/write`, `resourceProvider` igual a `Microsoft.Storage` e `status` igual a `Succeeded` |
| Fonte do tópico limitada ao grupo de recursos | `topic` do grupo autorizado e `data.subscriptionId` compatível com o ID configurado |

A inscrição entrega um evento por lote. O binding Python v2 fornece o envelope como `EventGridEvent` e o corpo por `get_json()`. A função valida os campos usados na decisão e descarta sinais fora do contrato sem consultar o ARM. Um `dataVersion` novo aparece como `unsupported_data_version`, o que exige revisão do contrato. [Esquema de eventos de grupo de recursos](https://learn.microsoft.com/en-us/azure/event-grid/event-schema-resource-groups) · [Filtros](https://learn.microsoft.com/en-us/azure/event-grid/event-filtering) · [Trigger Python](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-event-grid-trigger)

O cliente consulta o endpoint público do ARM com API `2025-06-01` e o ID vindo da configuração da Function. O PATCH contém exclusivamente `properties.allowBlobPublicAccess`. Uma resposta sem valor booleano ou uma leitura posterior diferente de `false` gera erro operacional. [Get Properties](https://learn.microsoft.com/en-us/rest/api/storagerp/storage-accounts/get-properties?view=rest-storagerp-2025-06-01) · [Update](https://learn.microsoft.com/en-us/rest/api/storagerp/storage-accounts/update?view=rest-storagerp-2025-06-01)

## Identidades e permissões

| Identidade | Ação ou papel | Escopo e motivo |
| --- | --- | --- |
| Function, identidade gerenciada atribuída pelo usuário | `Microsoft.Storage/storageAccounts/read` | Conta monitorada. Leitura das propriedades ARM nos dois modos |
| Mesma identidade | `Microsoft.Storage/storageAccounts/write` | Conta monitorada. Atribuição criada apenas com `remediation_enabled = true` |
| Mesma identidade | `Storage Blob Data Owner` e `Storage Table Data Contributor` | Storage do host. Runtime, pacote de implantação e diagnóstico do host |
| Mesma identidade | `Monitoring Metrics Publisher` | Recurso do Application Insights. Ingestão de telemetria por Microsoft Entra ID |
| Tópico Event Grid, identidade gerenciada de sistema | `Storage Blob Data Contributor` | Contêiner privado `eventgrid-deadletter` no Storage do host. Armazena eventos cuja entrega falhou |
| Serviço Event Grid | Acesso à chave do trigger concedido pelo provedor registrado | Endpoint nativo da Function. O Azure gerencia a chave usada na entrega |

Os papéis personalizados têm o grupo de laboratório como escopo atribuível e só são atribuídos à conta monitorada. Eles contêm ações de gerenciamento e concedem acesso a propriedades da conta. O ARM autoriza `storageAccounts/write` no recurso inteiro. A restrição a uma propriedade fica no payload do código. A identidade de remediação fica sem `listKeys` e sem papéis de dados na conta monitorada. [Definições de papéis no Azure](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-definitions) · [Ações de Azure Storage](https://learn.microsoft.com/pt-br/azure/role-based-access-control/permissions/storage)

As duas contas bloqueiam Shared Key e acesso anônimo a contêineres. A conta monitorada bloqueia a rede pública e define firewall `Deny` sem bypass. O Storage do host fica acessível por rede pública autenticada para o runtime Flex, o pacote e dead-letter, com contêineres privados e autorização Entra ID. A Function usa HTTPS e recebe o trigger com autenticação nativa do Event Grid. As exceções do Trivy são locais aos recursos em `infra/main.tf`. `AZU-0010` preserva o bloqueio de bypass no laboratório e `AZU-0012` registra a decisão de rede do host, que opera sem VNet. [Conexões do host por identidade](https://learn.microsoft.com/en-us/azure/azure-functions/manage-connections?tabs=host%2Cidentity) · [Papéis para destinos do Event Grid](https://learn.microsoft.com/en-us/azure/event-grid/add-identity-roles)

## Entrega, falhas e cobertura

- **Idempotência pelo estado.** Event Grid pode entregar novamente e fora de ordem. Cada execução lê a conta. Uma duplicata ou o evento gerado pelo próprio PATCH encontra `false` e termina com `compliant`. Se houve um novo desvio, um evento atrasado pode corrigi-lo. Duas execuções concorrentes podem ler `true` e enviar o mesmo PATCH convergente para `false`. [Entrega e retentativas](https://learn.microsoft.com/en-us/azure/event-grid/delivery-and-retry)
- **Falha verificável.** Erros do ARM registram etapa, motivo e status e são relançados ao runtime. A inscrição configura até 10 tentativas e TTL de 60 minutos. Quando uma entrega falha definitivamente, o serviço pode gravá-la em dead-letter. As decisões da função vão para `AppTraces`. O diagnóstico do Event Grid registra `DeliveryFailures` no workspace. [Erros e retentativas em Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-error-pages) · [Diagnóstico do tópico](https://learn.microsoft.com/en-us/azure/azure-monitor/reference/supported-logs/microsoft-eventgrid-systemtopics-logs)
- **Cobertura.** O gatilho acompanha escritas ARM bem-sucedidas na conta autorizada. Leituras de blobs, SAS, permissões de contêiner, endpoints de site estático e alterações fora da conta ficam fora do caso. Desvios anteriores à inscrição, eventos descartados e eventos perdidos durante uma interrupção exigem verificação direta do estado. A janela entre o desvio e a correção depende da entrega e da disponibilidade dos serviços. Uma Azure Policy com efeito `deny`, onde aplicável, bloquearia o desvio antes da escrita. [Tipos e limites da fonte](https://learn.microsoft.com/en-us/azure/event-grid/event-schema-resource-groups) · [Prevenção de acesso anônimo](https://learn.microsoft.com/en-us/azure/storage/blobs/anonymous-read-access-prevent)
- **Dono da configuração.** Terraform declara o baseline `false`. Um `apply` durante um desvio também pode restaurar a propriedade. A demonstração Azure estabelece a configuração do modo antes de cada nova injeção de desvio, preservando a distinção entre a ação do Terraform e a ação da Function.
