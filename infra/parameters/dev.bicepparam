using '../main.bicep'

// Non-sensitive defaults only. All IDs and secrets are passed via CLI.
param environmentName = 'dev'
param location = 'koreacentral'
param storageAccountName = 'stwsportaldev'
