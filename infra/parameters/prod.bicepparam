using '../main.bicep'

// =============================================================================
// Non-sensitive defaults
// =============================================================================
param environmentName = 'prod'
param location = 'koreacentral'
param storageAccountName = 'stworkshopdataprod'
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
// Pass the exact image tag to prevent rollback to placeholder on re-deployment.
// Set IMAGE_TAG to the currently running tag (e.g. the Git SHA) before deploying.
param imageTag = readEnvironmentVariable('IMAGE_TAG', '')
param azureTenantId = readEnvironmentVariable('AZURE_TENANT_ID')
param azureClientId = readEnvironmentVariable('AZURE_CLIENT_ID', '')

// =============================================================================
// Secrets — read from environment variables
// =============================================================================
param spClientSecret = readEnvironmentVariable('AZURE_SP_CLIENT_SECRET')
param acsConnectionString = readEnvironmentVariable('ACS_CONNECTION_STRING')
param ghcrToken = readEnvironmentVariable('GHCR_TOKEN')
param workshopAttendeesGroupId = readEnvironmentVariable('WORKSHOP_ATTENDEES_GROUP_ID', '')
