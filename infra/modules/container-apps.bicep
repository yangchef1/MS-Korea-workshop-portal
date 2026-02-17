// =============================================================================
// Container Apps Environment + Backend Container App
// =============================================================================

@description('Environment name for scaling and naming.')
@allowed(['dev', 'prod'])
param environmentName string

@description('Azure region.')
param location string

@description('ACR login server URL (e.g., myacr.azurecr.io).')
param acrLoginServer string

@description('ACR name for role assignment.')
param acrName string

@description('Subscription IDs for workshop resource provisioning.')
param subscriptionIds array

@description('SP tenant ID.')
param tenantId string

@description('SP client ID.')
param spClientId string

@description('SP domain (e.g., yourdomain.onmicrosoft.com).')
param spDomain string

@secure()
@description('SP client secret.')
param spClientSecret string

@secure()
@description('ACS connection string.')
param acsConnectionString string

@description('Table Storage account name.')
param storageAccountName string

@description('Email sender address.')
param emailSender string = ''

@description('MSAL tenant ID for JWT validation.')
param azureTenantId string = tenantId

@description('MSAL client ID for JWT validation.')
param azureClientId string = ''

@description('Container image tag.')
param imageTag string = 'latest'

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
var appName = 'ca-workshop-backend-${environmentName}'
var envName = 'cae-workshop-${environmentName}'
var logAnalyticsName = 'log-workshop-${environmentName}'
var allowedSubsJoined = join(subscriptionIds, ',')

var minReplicas = environmentName == 'prod' ? 1 : 0
var maxReplicas = environmentName == 'prod' ? 3 : 1

// ---------------------------------------------------------------------------
// Log Analytics Workspace
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Container Apps Environment
// ---------------------------------------------------------------------------
resource containerAppEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// Backend Container App
// ---------------------------------------------------------------------------
resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      registries: [
        {
          server: acrLoginServer
          identity: 'system'
        }
      ]
      secrets: [
        {
          name: 'sp-client-secret'
          value: spClientSecret
        }
        {
          name: 'acs-conn-str'
          value: acsConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: '${acrLoginServer}/workshop-backend:${imageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_SP_SUBSCRIPTION_ID', value: subscriptionIds[0] }
            { name: 'ALLOWED_SUBSCRIPTION_IDS', value: allowedSubsJoined }
            { name: 'AZURE_SP_TENANT_ID', value: tenantId }
            { name: 'AZURE_SP_CLIENT_ID', value: spClientId }
            { name: 'AZURE_SP_CLIENT_SECRET', secretRef: 'sp-client-secret' }
            { name: 'AZURE_SP_DOMAIN', value: spDomain }
            { name: 'AZURE_TENANT_ID', value: azureTenantId }
            { name: 'AZURE_CLIENT_ID', value: azureClientId }
            { name: 'TABLE_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'ACS_CONNECTION_STRING', secretRef: 'acs-conn-str' }
            { name: 'EMAIL_SENDER', value: emailSender }
            { name: 'LOG_FORMAT', value: 'json' }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// ACR Pull role assignment for Container App Managed Identity
// ---------------------------------------------------------------------------
// AcrPull built-in role ID
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acrResource 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acrResource.id, containerApp.id, acrPullRoleId)
  scope: acrResource
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output appName string = containerApp.name
output principalId string = containerApp.identity.principalId
