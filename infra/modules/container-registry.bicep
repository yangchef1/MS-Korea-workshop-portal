// =============================================================================
// Azure Container Registry
// =============================================================================

@description('ACR name. Must be globally unique, 5-50 alphanumeric.')
param acrName string

@description('Azure region.')
param location string

@description('ACR SKU.')
@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Basic'

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
  }
  tags: {
    project: 'workshop-portal'
  }
}

output loginServer string = acr.properties.loginServer
output acrId string = acr.id
output acrName string = acr.name
