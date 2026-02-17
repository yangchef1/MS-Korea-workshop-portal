// =============================================================================
// Azure Workshop Portal — Infrastructure Orchestration
// =============================================================================
// Entry point for deploying all portal infrastructure via Bicep modules.
// Usage:
//   az deployment sub create \
//     --location koreacentral \
//     --template-file infra/main.bicep \
//     --parameters infra/parameters/dev.bicepparam \
//     spClientSecret=<secret> acsConnectionString=<secret>

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

@description('Azure Container Registry name.')
param acrName string

@description('Email sender address for Azure Communication Services.')
param emailSender string = ''

@description('MSAL tenant ID for JWT validation.')
param azureTenantId string = tenantId

@description('MSAL client ID for JWT validation.')
param azureClientId string = ''

@description('Custom domain for SWA (optional).')
param customDomain string = ''

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

// 2. Container Registry
module acr 'modules/container-registry.bicep' = {
  name: 'acr-${environmentName}'
  scope: portalRg
  params: {
    acrName: acrName
    location: location
  }
}

// 3. Communication Services
module communication 'modules/communication.bicep' = {
  name: 'acs-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: 'global' // ACS is a global resource
  }
}

// 4. Container Apps (Backend)
module containerApps 'modules/container-apps.bicep' = {
  name: 'ca-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: location
    acrLoginServer: acr.outputs.loginServer
    acrName: acrName
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
  }
}

// 5. Static Web App + Linked Backend
module swa 'modules/static-web-app.bicep' = {
  name: 'swa-${environmentName}'
  scope: portalRg
  params: {
    environmentName: environmentName
    location: location
    backendFqdn: containerApps.outputs.fqdn
  }
}

// 6. Function App (Workshop Cleanup)
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
output acrLoginServer string = acr.outputs.loginServer
output containerAppFqdn string = containerApps.outputs.fqdn
output swaDefaultHostname string = swa.outputs.defaultHostname
output swaDeploymentToken string = swa.outputs.deploymentToken
output functionAppName string = functionApp.outputs.functionAppName
