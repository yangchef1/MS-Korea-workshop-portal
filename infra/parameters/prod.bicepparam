using '../main.bicep'

// =============================================================================
// Non-sensitive defaults
// =============================================================================
param environmentName = 'prod'
param location = 'koreacentral'
param storageAccountName = 'stwsportalprod'
param emailSender = ''

// =============================================================================
// IDs / config — read from environment variables (never hardcode real values)
// Set these env vars before running `az deployment sub create`.
// =============================================================================
param subscriptionIds = [readEnvironmentVariable('AZURE_SUBSCRIPTION_ID')]
param tenantId = readEnvironmentVariable('AZURE_SP_TENANT_ID')
param spClientId = readEnvironmentVariable('AZURE_SP_CLIENT_ID')
param spDomain = readEnvironmentVariable('AZURE_SP_DOMAIN')
param ghcrImage = readEnvironmentVariable('GHCR_IMAGE')
param azureTenantId = readEnvironmentVariable('AZURE_TENANT_ID')
param azureClientId = readEnvironmentVariable('AZURE_CLIENT_ID', '')

// =============================================================================
// Secrets — read from environment variables
// =============================================================================
param spClientSecret = readEnvironmentVariable('AZURE_SP_CLIENT_SECRET')
param acsConnectionString = readEnvironmentVariable('ACS_CONNECTION_STRING')
param ghcrToken = readEnvironmentVariable('GHCR_TOKEN')
