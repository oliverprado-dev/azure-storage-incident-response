# Implantação no Azure

## Pré-requisitos

- Bash, Python 3.12+, Terraform 1.14+ e Azure CLI atual, com `az functionapp list-flexconsumption-locations` disponível. A Function usa Linux, Python 3.12 e plano Flex Consumption (FC1). [Gerenciar Flex Consumption](https://learn.microsoft.com/pt-br/azure/azure-functions/flex-consumption-how-to)
- Assinatura de laboratório no Azure público, com quota disponível para Flex Consumption. Use um grupo dedicado gerenciado pelo Terraform e uma região com suporte. Verifique políticas que exijam rede privada no host ou impeçam a alteração de teste.
- Permissões de implantação para gerenciar o grupo, os recursos e a identidade da Function. O operador também precisa de `Microsoft.Authorization/roleDefinitions/write` e `delete` para os papéis personalizados e `Microsoft.Authorization/roleAssignments/write` e `delete` para as atribuições. Um exemplo é `Contributor` e `User Access Administrator` em uma assinatura dedicada ao laboratório. O registro dos provedores requer permissão na assinatura. Para consultar o workspace, use uma identidade com acesso de leitura aos logs, por exemplo `Log Analytics Reader`. [Permissões de papéis personalizados](https://learn.microsoft.com/en-us/azure/role-based-access-control/custom-roles) · [Papéis de acesso privilegiado](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/privileged) · [Acesso aos logs](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/manage-access)
- O estado do Terraform é local neste laboratório e fica fora do Git. Guarde `infra/terraform.tfstate` e `infra/terraform.tfvars` até concluir a limpeza.

## 1. Provisione a base em dry-run

Execute na raiz do repositório. Se outra equipe registrar provedores na assinatura, peça a ela para registrar os provedores listados e confira o estado `Registered`.

```bash
az login
az account list --output table
read -r -p 'ID da assinatura de laboratório: ' SUBSCRIPTION_ID
az account set --subscription "$SUBSCRIPTION_ID"
az functionapp list-flexconsumption-locations --output table

for provider in Microsoft.Storage Microsoft.Web Microsoft.ManagedIdentity \
  Microsoft.Insights Microsoft.OperationalInsights Microsoft.EventGrid; do
  az provider register --namespace "$provider" --wait
done
```

Use `westeurope` se a região estiver disponível na assinatura. A referência das variáveis está em [terraform.tfvars.example](../infra/terraform.tfvars.example). Gere o arquivo uma vez e preserve o sufixo enquanto o laboratório existir.

```bash
if [[ ! -f infra/terraform.tfvars ]]; then
  SUFFIX="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  cat > infra/terraform.tfvars <<EOF_VARS
subscription_id            = "$SUBSCRIPTION_ID"
name_suffix                = "$SUFFIX"
location                   = "westeurope"
event_subscription_enabled = false
remediation_enabled        = false
EOF_VARS
fi

terraform -chdir=infra init -lockfile=readonly
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra plan -out=base.tfplan
terraform -chdir=infra apply base.tfplan
```

## 2. Publique a função e conecte o Event Grid

```bash
bash scripts/deploy-function.sh
```

O script gera o ZIP com `host.json` na raiz, faz One Deploy com build remoto para instalar as dependências e consulta o ARM até encontrar o binding `eventGridTrigger` de `GuardStorage`. O endpoint nativo só pode ser configurado depois que a função estiver disponível. Se o deploy acusar falha de acesso ao Storage logo após a criação das atribuições, confira o RBAC, aguarde a propagação e execute o script novamente. [One Deploy no Flex](https://learn.microsoft.com/en-us/azure/azure-functions/functions-deployment-technologies) · [Deploy Python pelo Azure CLI](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)

Edite `infra/terraform.tfvars` para `event_subscription_enabled = true`. Preserve `remediation_enabled = false`.

```bash
terraform -chdir=infra plan -out=events.tfplan
terraform -chdir=infra apply events.tfplan

RG="$(terraform -chdir=infra output -raw resource_group_name)"
TOPIC="$(terraform -chdir=infra output -raw eventgrid_system_topic_name)"
az eventgrid system-topic event-subscription show \
  --resource-group "$RG" --system-topic-name "$TOPIC" --name guard-storage \
  --query '{state:provisioningState,destination:destination.endpointType,schema:eventDeliverySchema,filter:filter}'
```

Confira `Succeeded`, destino `AzureFunction`, esquema `EventGridSchema` e os filtros de evento, assunto e operação. [Comandos do Event Grid](https://learn.microsoft.com/en-us/cli/azure/eventgrid/system-topic/event-subscription)

## 3. Reproduza o desvio

Use apenas a conta dedicada criada pelo Terraform. As próximas saídas são **resultados esperados** para conferir na sua assinatura.

```bash
LAB_ID="$(terraform -chdir=infra output -raw lab_storage_account_id)"
CONTAINER_ID="$(terraform -chdir=infra output -raw lab_container_id)"
WORKSPACE="$(terraform -chdir=infra output -raw log_analytics_workspace_id)"

lab_state() {
  az storage account show --ids "$LAB_ID" \
    --query '{allowBlobPublicAccess:allowBlobPublicAccess,publicNetworkAccess:publicNetworkAccess}'
  az rest --method get \
    --url "https://management.azure.com${CONTAINER_ID}?api-version=2025-06-01" \
    --query '{container:name,publicAccess:properties.publicAccess}'
}

# 1. Registre o baseline. A propriedade deve estar false.
lab_state

# 2. Introduza o desvio no plano de controle, mantendo a rede e o contêiner privados.
az storage account update --ids "$LAB_ID" --allow-blob-public-access true --output none
lab_state
```

A conta deve retornar `allowBlobPublicAccess: true` em dry-run. Confira `publicNetworkAccess: Disabled` e `publicAccess: None` no contêiner. No workspace, abra **Logs** e execute [decisions.kql](queries/decisions.kql), ou use a CLI.

```bash
az monitor log-analytics query --workspace "$WORKSPACE" \
  --analytics-query "$(cat docs/queries/decisions.kql)" --output table
```

Procure `mode=dry-run`, `decision=detect`, `result=would_remediate` e `before=true`. Registre `event_id` e `correlation_id`. Pode haver atraso na entrega e na ingestão. [Consulta via Azure CLI](https://learn.microsoft.com/en-us/cli/azure/monitor/log-analytics#az-monitor-log-analytics-query)

### Ative a remediação e faça uma nova alteração

Restaure o baseline manualmente antes de trocar o modo. Assim a atualização que dispara a verificação ocorre depois da mudança de configuração da Function.

```bash
az storage account update --ids "$LAB_ID" --allow-blob-public-access false --output none
lab_state
```

Edite `infra/terraform.tfvars` para `remediation_enabled = true`. Preserve `event_subscription_enabled = true`.

```bash
terraform -chdir=infra plan -out=enforce.tfplan
terraform -chdir=infra apply enforce.tfplan

az storage account update --ids "$LAB_ID" --allow-blob-public-access true --output none
```

Aguarde o processamento. Execute `lab_state` e repita a consulta KQL até localizar o novo evento. Registre `mode=enforce`, `decision=remediate`, `result=verified`, `before=true` e `after=false`. O PATCH da Function gera outro evento de escrita, que pode aparecer como `no_action / compliant`. Confirme `false` no GET independente e o contêiner ainda privado. Quando a atribuição de escrita acabou de ser criada, uma resposta 403 pode indicar propagação de RBAC. Investigue com o [runbook](runbook.md).

| Evidência | Onde coletar |
| --- | --- |
| Valor antes, desvio em dry-run e valor final | Saídas de `lab_state` |
| Evento recebido | `event_id`, `correlation_id` e `resource_id` em `AppTraces` |
| Autor da escrita original e da correção | Activity Log por correlação ou ID da conta |
| Decisão e resultado | Campos `mode`, `decision`, `result`, `before` e `after` em `AppTraces` |

## 4. Desmonte o ambiente

Use a mesma assinatura e os mesmos arquivos de variáveis e estado. Confira o plano de destruição antes de confirmar.

```bash
RG="$(terraform -chdir=infra output -raw resource_group_name)"
terraform -chdir=infra plan -destroy -out=destroy.tfplan
terraform -chdir=infra apply destroy.tfplan
az group exists --name "$RG"
```

O último comando deve retornar `false`. Para a mesma operação em um único comando interativo, use `terraform -chdir=infra destroy`. Depois de confirmar a remoção, descarte as cópias locais dos planos e do estado conforme sua política de retenção.

## Estimativa de custos

Estimativa de ordem de grandeza em USD para um mês em **West Europe**, pagamento conforme o uso, com uma Function de 512 MB sem instâncias Always Ready e o grupo dedicado do laboratório. Premissas de 1.000 invocações de até 2 s em média, 2.000 operações faturáveis do Event Grid, 50 MB de logs e até 0,1 GB-mês de blobs. A tabela usa tarifas de varejo consultadas em 9 de novembro de 2026. [API de preços de varejo do Azure](https://learn.microsoft.com/pt-br/rest/api/cost-management/retail-prices/azure-retail-prices)

| Componente | Estimativa sob essas premissas |
| --- | --- |
| Functions Flex | 1.000 GB-s e 1.000 execuções. Dentro da franquia on-demand se houver saldo. Cerca de US$ 0,03 a preço cheio. [Preços de Functions](https://azure.microsoft.com/en-us/pricing/details/functions/) |
| Event Grid | 2.000 operações. Cerca de US$ 0,001 a preço cheio. A franquia pode cobrir o volume. [Preços de Event Grid](https://azure.microsoft.com/en-us/pricing/details/event-grid/) |
| Log Analytics e Application Insights | 0,05 GB de ingestão em Analytics Logs. Cerca de US$ 0,15 a US$ 2,99/GB, antes da franquia aplicável. O workspace usa retenção de 30 dias. [Preços de Azure Monitor](https://azure.microsoft.com/en-us/pricing/details/monitor/) |
| Storage LRS | Cerca de US$ 0,002 em capacidade de Blob Hot. Reserve cerca de US$ 0,10 para a capacidade e o baixo volume de transações, assumindo até 10 mil escritas e 10 mil leituras no mês. [Preços de Blob Storage](https://azure.microsoft.com/en-us/pricing/details/storage/blobs/) |

**Estimativa total abaixo de US$ 1/mês** com esse volume, sem impostos ou egress relevante. Consumo agregado da assinatura, retentativas, tráfego, volume de logs, câmbio e oferta de cobrança podem alterar o total.
