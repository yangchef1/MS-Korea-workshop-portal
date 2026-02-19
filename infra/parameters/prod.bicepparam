using '../main.bicep'

param environmentName = 'prod'
param location = 'koreacentral'
// Add subscription IDs as needed for multi-subscription support
param subscriptionIds = ['00000000-0000-0000-0000-000000000000']
param tenantId = '00000000-0000-0000-0000-000000000000'
param spClientId = '00000000-0000-0000-0000-000000000000'
param spDomain = 'yourdomain.onmicrosoft.com'
// Must match existing Storage Account name to preserve data (idempotent deployment)
param storageAccountName = 'stwsportalprod'
param ghcrImage = 'ghcr.io/<owner>/workshop-backend'
param emailSender = ''
param azureTenantId = '00000000-0000-0000-0000-000000000000'
param azureClientId = '00000000-0000-0000-0000-000000000000'
