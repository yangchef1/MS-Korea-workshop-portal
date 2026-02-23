// =============================================================================
// Function App — Workshop Cleanup Timer
// =============================================================================

@description('Environment name for naming and configuration.')
@allowed(['dev', 'prod'])
param environmentName string

@description('Azure region.')
param location string

@description('Subscription IDs for multi-sub resource cleanup.')
param subscriptionIds array

@description('SP tenant ID.')
param tenantId string

@description('SP client ID.')
param spClientId string

@secure()
@description('SP client secret.')
param spClientSecret string

@description('SP domain.')
param spDomain string

@description('Workshop Table Storage account name.')
param storageAccountName string

@description('Workshop Table Storage account resource ID.')
param workshopStorageAccountId string

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
var functionAppName = 'func-workshop-cleanup-${environmentName}'
var appServicePlanName = 'asp-workshop-cleanup-${environmentName}'
var funcStorageName = 'stfuncws${environmentName}' // Separate storage for Functions runtime
var allowedSubsJoined = join(subscriptionIds, ',')

// ---------------------------------------------------------------------------
// Storage Account for Functions runtime (separate from workshop data)
// ---------------------------------------------------------------------------
resource funcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: funcStorageName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowSharedKeyAccess: false
  }
}

// ---------------------------------------------------------------------------
// App Service Plan (Consumption Y1)
// ---------------------------------------------------------------------------
resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: appServicePlanName
  location: location
  kind: 'functionapp,linux'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

// ---------------------------------------------------------------------------
// Function App
// ---------------------------------------------------------------------------
resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: funcStorage.name }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'ALLOWED_SUBSCRIPTION_IDS', value: allowedSubsJoined }
        { name: 'AZURE_SP_TENANT_ID', value: tenantId }
        { name: 'AZURE_SP_CLIENT_ID', value: spClientId }
        { name: 'AZURE_SP_CLIENT_SECRET', value: spClientSecret }
        { name: 'AZURE_DOMAIN', value: spDomain }
        { name: 'TABLE_STORAGE_ACCOUNT', value: storageAccountName }
      ]
    }
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// RBAC role assignments for Function App managed identity
// ---------------------------------------------------------------------------
resource funcStorageBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, functionApp.id, 'blob-owner')
  scope: funcStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Owner
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcStorageQueueContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, functionApp.id, 'queue-contributor')
  scope: funcStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88') // Storage Queue Data Contributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcStorageTableContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(funcStorage.id, functionApp.id, 'table-contributor')
  scope: funcStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '76199698-9eea-4c19-bc07-45e0e9d74c54') // Storage Table Data Contributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Reference to the existing workshop storage account
resource workshopStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

// Workshop data storage access (Tables) for Function App managed identity
resource workshopStorageTableContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workshopStorageAccountId, functionApp.id, 'workshop-table-contributor')
  scope: workshopStorage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '76199698-9eea-4c19-bc07-45e0e9d74c54') // Storage Table Data Contributor
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output principalId string = functionApp.identity.principalId
