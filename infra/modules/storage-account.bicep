// =============================================================================
// Storage Account + Table Service + Workshop Tables
// =============================================================================
// Idempotent: always declares the resource. ARM incremental deployment
// preserves existing data. Name is parameterised so that prod can point
// to the existing account while dev creates a fresh one.

@description('Storage Account name. Must be globally unique, 3-24 lowercase alphanumeric.')
param storageAccountName string

@description('Azure region.')
param location string

@description('Storage SKU. Must match existing account in prod.')
param storageSku string = 'Standard_LRS'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: storageSku
  }
  properties: {
    accessTier: 'Hot'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
  tags: {
    project: 'workshop-portal'
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

// Workshop portal tables — idempotent: if they already exist, ARM skips them.
resource workshopsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'workshops'
}

resource passwordsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'passwords'
}

resource templatesTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'templates'
}

resource usersTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'users'
}

output storageAccountName string = storageAccount.name
output storageAccountId string = storageAccount.id
