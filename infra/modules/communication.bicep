// =============================================================================
// Azure Communication Services
// =============================================================================

@description('Environment name for resource naming.')
param environmentName string

@description('Location for ACS (typically "global").')
param location string = 'global'

var acsName = 'acs-wsportal-${environmentName}'

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: acsName
  location: location
  properties: {
    dataLocation: 'Korea'
  }
  tags: {
    project: 'workshop-portal'
    environment: environmentName
  }
}

output acsName string = acs.name
output acsId string = acs.id
