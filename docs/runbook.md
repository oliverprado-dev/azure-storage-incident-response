# Runbook de resposta a desvio

## 1. Confirme o estado e delimite o incidente

Execute na raiz do repositório com a assinatura de laboratório ativa.

```bash
RG="$(terraform -chdir=infra output -raw resource_group_name)"
APP="$(terraform -chdir=infra output -raw function_app_name)"
LAB_ID="$(terraform -chdir=infra output -raw lab_storage_account_id)"
CONTAINER_ID="$(terraform -chdir=infra output -raw lab_container_id)"
WORKSPACE="$(terraform -chdir=infra output -raw log_analytics_workspace_id)"
TOPIC="$(terraform -chdir=infra output -raw eventgrid_system_topic_name)"
PRINCIPAL="$(terraform -chdir=infra output -raw function_principal_id)"

az storage account show --ids "$LAB_ID" \
  --query '{allowBlobPublicAccess:allowBlobPublicAccess,publicNetworkAccess:publicNetworkAccess}'
az rest --method get \
  --url "https://management.azure.com${CONTAINER_ID}?api-version=2025-06-01" \
  --query 'properties.publicAccess'
az monitor log-analytics query --workspace "$WORKSPACE" \
  --analytics-query "$(cat docs/queries/decisions.kql)" --output table
```

Registre horário UTC, ID da conta, valor da propriedade, configuração do contêiner e modo da função. Use o ID de correlação da decisão para localizar a escrita. O ID do evento serve para identificar entregas repetidas.

```bash
read -r -p 'ID de correlação exibido em AppTraces: ' CORRELATION_ID
az monitor activity-log list --correlation-id "$CORRELATION_ID" --offset 2h \
  --query '[].{time:eventTimestamp,caller:caller,action:operationName.value,status:status.value,resource:resourceId}' \
  --output table

# Histórico de escritas na conta, inclusive as iniciadas pela identidade da função.
az monitor activity-log list --resource-id "$LAB_ID" --offset 2h \
  --query "[?operationName.value=='Microsoft.Storage/storageAccounts/write'].{time:eventTimestamp,caller:caller,status:status.value,correlation:correlationId}" \
  --output table
```

Classifique a alteração como desvio de configuração. Para investigar uma possível exposição fora deste laboratório, determine quais contêineres aceitavam leitura anônima, se o endpoint era alcançável durante a janela e se os logs de acesso a blobs registram solicitações anônimas bem-sucedidas. Preserve horários e identificadores e oculte dados da assinatura e do operador em evidências públicas. [Consulta ao Activity Log](https://learn.microsoft.com/en-us/cli/azure/monitor/activity-log) · [Avaliação de acesso anônimo](https://learn.microsoft.com/en-us/azure/storage/blobs/anonymous-read-access-prevent)

## 2. Investigue a falha

| Sinal | Ação |
| --- | --- |
| `would_remediate` | Dry-run observou `true`. Confirme se esse é o modo planejado e restaure manualmente quando necessário. |
| `invalid_event` ou `unsupported_data_version` | Revise o esquema e a origem. Compare os campos registrados com a fonte ARM oficial e inspecione o payload em ambiente controlado. |
| `out_of_scope` | Compare `subject`, `topic`, `data.resourceUri` e `subscriptionId` com a conta prevista e com os filtros da inscrição. |
| `arm_error` em `read` ou `patch` com 401 ou 403 | Confira a identidade anexada, o escopo do RBAC, propagação, locks e Azure Policy. Use o Activity Log para distinguir bloqueios de política de falhas de autorização. |
| `arm_error` com `transport_failure`, 429 ou 5xx | Confira status dos serviços, conectividade de saída para o ARM e retentativas. Consulte o estado antes de reenviar uma correção. |
| `verification_failed` em `verify` | Consulte a propriedade e a sequência de escritas no Activity Log. Uma gravação concorrente pode ter reintroduzido o desvio. |
| Evento sem decisão | Verifique se há escrita bem-sucedida, se a inscrição está ativa e se o trigger foi indexado. Compare métricas de entrega e logs da Function. Em seguida, confira a ingestão do Application Insights. |
| Função ausente após o deploy | Examine o status do build remoto, o ZIP com `host.json` na raiz, o runtime Python 3.12 e os papéis de Blob e Table da identidade no Storage do host. |

```bash
az role assignment list --scope "$LAB_ID" --include-inherited \
  --query "[?principalId=='${PRINCIPAL}'].{role:roleDefinitionName,scope:scope}" --output table

az functionapp function show --resource-group "$RG" --name "$APP" \
  --function-name GuardStorage --query 'config.bindings[].type'

az eventgrid system-topic event-subscription show \
  --resource-group "$RG" --system-topic-name "$TOPIC" --name guard-storage \
  --query '{state:provisioningState,filter:filter,retry:retryPolicy}'

TOPIC_ID="$(az eventgrid system-topic show --resource-group "$RG" --name "$TOPIC" --query id -o tsv)"
az monitor metrics list --resource "$TOPIC_ID" \
  --metric DeliveryAttemptFailCount DeadLetteredCount --aggregation Total --interval PT5M

az monitor log-analytics query --workspace "$WORKSPACE" \
  --analytics-query "$(cat docs/queries/delivery-failures.kql)" --output table
```

Se houver dead-letter, liste os blobs com uma identidade de operador que tenha `Storage Blob Data Reader` no contêiner. O material de diagnóstico pode conter claims e IDs de atores. Trate-o como evidência restrita. A decisão de corrigir deve usar um novo GET do estado da conta.

```bash
HOST_STORAGE="$(terraform -chdir=infra output -raw runtime_storage_account_name)"
az storage blob list --account-name "$HOST_STORAGE" --container-name eventgrid-deadletter \
  --auth-mode login --query '[].{blob:name,modified:properties.lastModified}' --output table
```

[Retentativas e dead-letter do Event Grid](https://learn.microsoft.com/en-us/azure/event-grid/manage-event-delivery)

## 3. Pause a remediação

1. Mude imediatamente o app setting para dry-run. A atualização reinicia o app. Uma invocação já em andamento pode concluir durante a transição.
2. Edite `infra/terraform.tfvars` para `remediation_enabled = false` e preserve `event_subscription_enabled = true`. Revise o plano e aplique para revogar a atribuição de escrita e manter as observações. Se a conta estiver em desvio, o plano também pode incluir a restauração do baseline.
3. Verifique o modo e a remoção da atribuição de escrita. Se o incidente exigir interromper o processamento por completo, pare a Function App, faça as mudanças e volte a iniciá-la em dry-run. A pausa pode gerar retentativas ou dead-letter.

```bash
az functionapp config appsettings set --resource-group "$RG" --name "$APP" \
  --settings REMEDIATION_ENABLED=false --output none

# Após editar o arquivo de variáveis.
terraform -chdir=infra plan -out=pause.tfplan
terraform -chdir=infra apply pause.tfplan

az functionapp config appsettings list --resource-group "$RG" --name "$APP" \
  --query "[?name=='REMEDIATION_ENABLED'].value" --output tsv
az role assignment list --scope "$LAB_ID" --include-inherited \
  --query "[?principalId=='${PRINCIPAL}'].roleDefinitionName" --output tsv
```

Para conter o desvio com um operador autorizado, envie a alteração no ARM e confirme a leitura.

```bash
az storage account update --ids "$LAB_ID" --allow-blob-public-access false --output none
az storage account show --ids "$LAB_ID" --query allowBlobPublicAccess --output tsv
```

Ao retomar, confirme `false` no baseline, revise o escopo, habilite a escrita pelo Terraform e repita o [teste de remediação](deployment.md#ative-a-remediação-e-faça-uma-nova-alteração).
