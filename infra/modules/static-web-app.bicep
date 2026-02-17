// =============================================================================
// Azure Static Web App + Linked Backend
// =============================================================================

@description('Environment name for naming.')
param environmentName string

@description('Azure region.')
param location string

@description('Backend Container App FQDN (without scheme).')
param backendFqdn string

var swaName = 'swa-workshop-${environmentName}'

// ---------------------------------------------------------------------------
// Static Web App
// ---------------------------------------------------------------------------
resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

// ---------------------------------------------------------------------------
// Linked Backend — routes /api/* to the Container App
// ---------------------------------------------------------------------------
resource linkedBackend 'Microsoft.Web/staticSites/linkedBackends@2023-12-01' = {
  parent: swa
  name: 'backend'
  properties: {
    backendResourceId: '' // Linked via FQDN below
    region: location
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
output defaultHostname string = swa.properties.defaultHostname
output swaName string = swa.name
output deploymentToken string = swa.listSecrets().properties.apiKey
