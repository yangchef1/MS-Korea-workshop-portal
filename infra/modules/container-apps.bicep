// =============================================================================
// Container Apps Environment + Backend Container App
// =============================================================================

@description('Environment name for scaling and naming.')
@allowed(['dev', 'prod'])
param environmentName string

@description('Azure region.')
param location string

@description('GHCR container image reference (e.g., ghcr.io/<owner>/workshop-backend).')
param ghcrImage string

@secure()
@description('GHCR Personal Access Token for pulling container images.')
param ghcrToken string

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

@description('Container image tag. Set to empty string to use a placeholder image for initial deployment.')
param imageTag string = ''

@description('Allowed CORS origins (comma-separated).')
param allowedOrigins string = ''

@description('Container Apps subnet resource ID for VNet integration. Required for Private Endpoint connectivity to Storage.')
param containerAppsSubnetId string

// ---------------------------------------------------------------------------
// Derived values
// ---------------------------------------------------------------------------
// Use Azure quickstart placeholder when no real image is available yet.
var usePlaceholder = empty(imageTag)
var containerImage = usePlaceholder ? 'mcr.microsoft.com/k8se/quickstart:latest' : '${ghcrImage}:${imageTag}'
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
    vnetConfiguration: {
      // Subnet must be delegated to Microsoft.App/environments.
      // internal: false preserves external ingress so SWA can reach the backend.
      infrastructureSubnetId: containerAppsSubnetId
      internal: false
    }
    // VNet-integrated CAEs require at least one workload profile.
    // Consumption is the serverless default (no dedicated nodes, pay-per-use).
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
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
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
        corsPolicy: {
          allowedOrigins: ['*'] // Restrict to SWA hostname after initial deployment
          allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS']
          allowedHeaders: ['*']
          allowCredentials: true
          maxAge: 86400
        }
      }
      registries: usePlaceholder ? [] : [
        {
          server: 'ghcr.io'
          username: 'ghcr-pull'
          passwordSecretRef: 'ghcr-token'
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
        {
          name: 'ghcr-token'
          value: ghcrToken
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionIds[0] }
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
            { name: 'ALLOWED_ORIGINS', value: allowedOrigins }
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
// Cleanup Job — replaces Azure Function timer (Phase 1)
// ---------------------------------------------------------------------------
resource cleanupJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-workshop-cleanup-${environmentName}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: '0 * * * *' // Hourly polling; cleanup.py checks end_date + 1h < now
      }
      registries: usePlaceholder ? [] : [
        {
          server: 'ghcr.io'
          username: 'ghcr-pull'
          passwordSecretRef: 'ghcr-token'
        }
      ]
      secrets: [
        {
          name: 'sp-client-secret'
          value: spClientSecret
        }
        {
          name: 'ghcr-token'
          value: ghcrToken
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'cleanup'
          image: containerImage
          command: [
            'python'
            '-m'
            'app.jobs.cleanup'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionIds[0] }
            { name: 'ALLOWED_SUBSCRIPTION_IDS', value: allowedSubsJoined }
            { name: 'AZURE_SP_TENANT_ID', value: tenantId }
            { name: 'AZURE_SP_CLIENT_ID', value: spClientId }
            { name: 'AZURE_SP_CLIENT_SECRET', secretRef: 'sp-client-secret' }
            { name: 'AZURE_SP_DOMAIN', value: spDomain }
            { name: 'TABLE_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'LOG_FORMAT', value: 'json' }
          ]
        }
      ]
    }
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// Provision Job — pre-provisions scheduled workshops (Phase 2)
// ---------------------------------------------------------------------------
resource provisionJob 'Microsoft.App/jobs@2024-03-01' = {
  name: 'job-workshop-provision-${environmentName}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    environmentId: containerAppEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: 3600 // Provisioning can take longer than cleanup
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: '0 * * * *' // Hourly polling; provision.py checks start_date - 1h <= now
      }
      registries: usePlaceholder ? [] : [
        {
          server: 'ghcr.io'
          username: 'ghcr-pull'
          passwordSecretRef: 'ghcr-token'
        }
      ]
      secrets: [
        {
          name: 'sp-client-secret'
          value: spClientSecret
        }
        {
          name: 'ghcr-token'
          value: ghcrToken
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'provision'
          image: containerImage
          command: [
            'python'
            '-m'
            'app.jobs.provision'
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionIds[0] }
            { name: 'ALLOWED_SUBSCRIPTION_IDS', value: allowedSubsJoined }
            { name: 'AZURE_SP_TENANT_ID', value: tenantId }
            { name: 'AZURE_SP_CLIENT_ID', value: spClientId }
            { name: 'AZURE_SP_CLIENT_SECRET', secretRef: 'sp-client-secret' }
            { name: 'AZURE_SP_DOMAIN', value: spDomain }
            { name: 'TABLE_STORAGE_ACCOUNT', value: storageAccountName }
            { name: 'LOG_FORMAT', value: 'json' }
          ]
        }
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
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output appName string = containerApp.name
output principalId string = containerApp.identity.principalId
// Exposed for Phase 2 — Container Apps Job will reference this environment.
output containerAppEnvId string = containerAppEnv.id
output cleanupJobName string = cleanupJob.name
output cleanupJobPrincipalId string = cleanupJob.identity.principalId
output provisionJobName string = provisionJob.name
output provisionJobPrincipalId string = provisionJob.identity.principalId
