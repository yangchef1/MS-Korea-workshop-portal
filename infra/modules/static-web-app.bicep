// =============================================================================
// Azure Static Web App
// =============================================================================

@description('Environment name for naming.')
param environmentName string

@description('Azure region.')
param location string

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
// Outputs
// ---------------------------------------------------------------------------
output defaultHostname string = swa.properties.defaultHostname
output swaName string = swa.name

#disable-next-line outputs-should-not-contain-secrets
output deploymentToken string = swa.listSecrets().properties.apiKey
