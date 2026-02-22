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

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
var functionAppName = 'func-wsportal-cleanup-${environmentName}'
var appServicePlanName = 'asp-wsportal-cleanup-${environmentName}'
var funcStorageName = 'stfunccleanup${environmentName}' // Separate storage for Functions runtime
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
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorage.name};EndpointSuffix=core.windows.net;AccountKey=${funcStorage.listKeys().keys[0].value}' }
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
// Outputs
// ---------------------------------------------------------------------------
output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output principalId string = functionApp.identity.principalId
