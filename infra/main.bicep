// =============================================================================
// Azure Workshop Portal — Infrastructure Orchestration
// =============================================================================
// Entry point for deploying all portal infrastructure via Bicep modules.
// Usage:
//   az deployment sub create \
//     --location koreacentral \
//     --template-file infra/main.bicep \
//     --parameters infra/parameters/dev.bicepparam \
//     spClientSecret=<secret> acsConnectionString=<secret> ghcrToken=<secret>

targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------
@description('Environment name used for resource naming and scaling.')
@allowed(['dev', 'prod'])
param environmentName string

@description('Primary Azure region for all resources.')
param location string = 'koreacentral'

@description('Subscription IDs where workshop resources are provisioned. Single-element array for single-sub; add elements for multi-sub.')
param subscriptionIds array

@description('Entra ID tenant for the Service Principal.')
param tenantId string

@description('Service Principal client (application) ID.')
param spClientId string

@description('Service Principal domain (e.g., yourdomain.onmicrosoft.com).')
param spDomain string

@secure()
@description('Service Principal client secret. Injected from CI/CD secrets.')
param spClientSecret string

@secure()
@description('Azure Communication Services connection string. Injected from CI/CD secrets.')
param acsConnectionString string

@description('Storage Account name. Must match existing account in prod to preserve data.')
param storageAccountName string

@description('GHCR container image reference (e.g., ghcr.io/<owner>/workshop-backend).')
param ghcrImage string

@secure()
@description('GHCR Personal Access Token for pulling container images. Injected from CI/CD secrets.')
param ghcrToken string

@description('Email sender address for Azure Communication Services.')
param emailSender string = ''

@description('MSAL tenant ID for JWT validation.')
param azureTenantId string = tenantId

@description('MSAL client ID for JWT validation.')
param azureClientId string = ''

@description('Resource group name for portal infrastructure.')
param resourceGroupName string = 'rg-workshop-portal-${environmentName}'

// ---------------------------------------------------------------------------
// Resource Group
// ---------------------------------------------------------------------------
resource portalRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    environment: environmentName
    project: 'workshop-portal'
  }
}

// ---------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------

// 1. Storage Account + Tables
module storage 'modules/storage-account.bicep' = {
  name: 'storage-${environmentName}'
  scope: portalRg
  params: {
    storageAccountName: storageAccountName
    location: location
  }
}

// 2. Communication Services
module communication 'modules/communication.bicep' = {
  name: 'acs-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: 'global' // ACS is a global resource
  }
}

// 3. Static Web App
// SWA Free tier is not available in koreacentral; eastasia is the closest supported region.
module swa 'modules/static-web-app.bicep' = {
  name: 'swa-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: 'eastasia'
  }
}

// 4. Container Apps (Backend)
module containerApps 'modules/container-apps.bicep' = {
  name: 'ca-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: location
    ghcrImage: ghcrImage
    ghcrToken: ghcrToken
    subscriptionIds: subscriptionIds
    tenantId: tenantId
    spClientId: spClientId
    spDomain: spDomain
    spClientSecret: spClientSecret
    acsConnectionString: acsConnectionString
    storageAccountName: storageAccountName
    emailSender: emailSender
    azureTenantId: azureTenantId
    azureClientId: azureClientId
    allowedOrigins: 'https://${swa.outputs.defaultHostname}'
  }
}

// 5. Function App (Workshop Cleanup)
module functionApp 'modules/function-app.bicep' = {
  name: 'func-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: location
    subscriptionIds: subscriptionIds
    tenantId: tenantId
    spClientId: spClientId
    spClientSecret: spClientSecret
    spDomain: spDomain
    storageAccountName: storageAccountName
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output storageAccountNameOutput string = storage.outputs.storageAccountName
output containerAppFqdn string = containerApps.outputs.fqdn
output backendUrl string = 'https://${containerApps.outputs.fqdn}'
output swaDefaultHostname string = swa.outputs.defaultHostname
output swaDeploymentToken string = swa.outputs.deploymentToken
output functionAppName string = functionApp.outputs.functionAppName
